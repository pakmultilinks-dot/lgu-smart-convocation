// Typed client for the LGU Smart Convocation backend.
// The base URL is read from the settings store on every call so the Admin
// console can change it without an app restart. QR payloads are opaque
// strings; all verification happens server side, nothing secret lives in
// this bundle.

import { getApiBaseUrl, noteUnreachableBaseUrl } from "../store/settings";
import { getAdminPin } from "../store/adminAccess";
import {
  clearScannerSession,
  getScannerSession,
  setScannerSession,
  type ScannerSession,
} from "../store/scannerSession";
import type { QueuedScan } from "../store/offlineQueue";

export interface Gate {
  id: number;
  code: string;
  label: string;
}

export type ScanMode = "entry" | "exit";
/** The two occasions of the annual cycle (Phase 29). A scan records which
 * one it admits; the backend refuses values outside this union. */
export type Occasion = "rehearsal" | "ceremony";
export type ScanLevel = "green" | "red" | "amber";

export interface ScanResult {
  // "busy" (Phase 22 §3) is a bounded, retryable SQLite contention answer.
  // It is NOT a failure and NOT an outcome: it means "ask again shortly".
  status: "ok" | "error" | "busy";
  level: ScanLevel;
  title: string;
  detail?: string;
  name?: string;
  sub?: string;
  gate?: string;
  time?: string;
}

export interface FeedItem {
  id: number;
  person_name: string;
  person_type: string;
  mode: string;
  gate_label: string;
  scanned_at: string;
  volunteer: string;
}

export interface DashboardData {
  /** Admin-configured expected attendance (0 = not set yet). */
  expected_attendance: number;
  /** True when expected_attendance > 0; false → explicit "not set" UI. */
  attendance_set: boolean;
  /** Student roster count (registrations) — distinct from the target. */
  student_roster_count: number;
  /** Default broadcast audience (all students in the roster). */
  announcement_audience_count: number;
  /** Roster gender splits (registration data, not live counts). */
  roster_male: number;
  roster_female: number;
  /** Guest registrations (passes created). */
  guest_registrations: number;
  inside_total: number;
  male: number;
  female: number;
  guests_inside: number;
  /** Phase 34 (Part F): convocation admissions are a SEPARATE ledger from
   * the legacy roster occupancy above. These are cumulative, entry-only
   * arrivals recorded against the convocation pass ledger (no exit exists
   * for LGU2 passes) — never merge them into "inside_total" (students whose
   * latest scan is an entry). Shown with their own honest labels. */
  ceremony_admitted: number;
  rehearsal_admitted: number;
  arrival_pct: number;
  busiest_gate: string;
  throughput: { gate: Gate; count: number }[];
  sync: { gate: Gate; last: string | null; count: number; entries: number; exits: number }[];
  feed: FeedItem[];
  /** Gate-activity window in minutes (server-configured, 35K Part J). */
  window_minutes: number;
  /** Phase 38 shared analytics (additive): attendees still outside the
      venue — null when the target is not set (never a fabricated 0). */
  remaining_attendance: number | null;
  /** Today's refused scans (every non-admitting verdict) ... */
  rejected_count: number;
  /** ... and their duplicate subset (ALREADY INSIDE/USED/ADMITTED/SYNCED). */
  duplicate_count: number;
  /** Hourly entry/exit trend for today with a running entry total. */
  trends: { hour: string; entries: number; exits: number; cumulative_entries: number }[];
  /** Server-suggested refresh cadence — clients clamp to [2000, 30000]. */
  poll_interval_ms: number;
  /** Cumulative admissions per occasion of the annual cycle (Phase 34). */
  admissions_by_occasion: { ceremony: number; rehearsal: number };
  /** Present only when the request carried ?occasion= (scope echo). */
  occasion_filter?: Occasion;
  occasion_admitted?: number;
  generated_at: string;
}

/** Event identity + shared operational config (GET /api/config, 35K). */
export interface AppConfig {
  app_name: string;
  university: string;
  motto: string;
  event: { name: string; year: string; datetime: string; venue: string };
  expected_attendance: number;
  attendance_set: boolean;
  student_roster_count: number;
  announcement_audience_count: number;
  guest_registrations: number;
  gates: Gate[];
  /** "demo" (record only) | "real" (delivery gateway not configured). */
  broadcast_mode: "demo" | "real";
  /** Gate-activity window in minutes — shared with backend queries. */
  gate_activity_window_minutes: number;
  /** Message character limit enforced server-side. */
  message_char_limit: number;
}

/** Per-gate audience breakdown for the by-gate composer (33-QA I15). */
export interface BroadcastGateAudience {
  id: number;
  label: string;
  count: number;
}

/** Announcement audience for the broadcast composer (35K Part I). */
export interface BroadcastAudience {
  ok: boolean;
  count: number;
  /** The rule that produced the count — never fabricated. */
  basis: string;
  /** Selected gates' own counts, largest first (absent/empty for "all"). */
  per_gate?: BroadcastGateAudience[];
}

/** Deterministic test record used by the scanner's Test Scan feature. */
export interface TestRecord {
  key: string;
  kind: "student" | "guest";
  label: string;
  payload: string;
}

export interface Guest {
  id: number;
  name: string;
  phone: string;
  host_roll_no: string;
  /** Host student's roster name; null when the roll has no roster record. */
  host_name?: string | null;
  /** Lifecycle state (Phase 34 Part C): "active" | "revoked". */
  status: string;
  used: boolean;
  /** Latest guest scan time (server PKT wall clock) when used, else null. */
  used_at?: string | null;
  /** Gate label of the latest guest scan when used, else null. */
  used_gate?: string | null;
}

export interface GuestRegistration {
  ok: boolean;
  gid?: number;
  payload?: string;
  error?: string;
}

export interface GuestPass {
  ok: boolean;
  gid: number;
  name: string;
  phone: string;
  host_roll_no: string;
  /** Host student's roster name; null when the roll has no roster record. */
  host_name?: string | null;
  /** Lifecycle state (Phase 34 Part C): "active" | "revoked". */
  status: string;
  used: boolean;
  payload: string;
}

/** Phase 34 (Part C): revoke an unused guest pass (scanner-staff only). */
export async function revokeGuestPass(gid: number): Promise<void> {
  const data = await request<{ ok: boolean; error?: string }>(
    `/api/guests/${gid}/revoke`,
    { method: "POST", headers: await scannerAuthHeaders() },
  );
  if (!data.ok) {
    throw new ApiError(data.error ?? "Guest pass could not be revoked.", 400);
  }
}

export interface BroadcastEntry {
  id: number;
  audience: string;
  message: string;
  sent_by: string;
  sent_at: string;
}

export interface BroadcastResponse {
  ok: boolean;
  note?: string;
  error?: string;
}

export class ApiError extends Error {
  status: number;
  /** Server machine code (Phase 5 student API: "unmatched",
      "cancelled", "claimed", "email_unavailable", ...). */
  code?: string;
  /** True when the backend answered and a retry may succeed (Phase 23 §2).
      A busy answer is transient contention, not a failure — the scanner
      must not mark the device offline or use the error haptic for it. */
  retryable?: boolean;
  /** The backend's own result body for a retryable answer, so the
      volunteer sees "TEMPORARILY BUSY" rather than a generic error. */
  result?: ScanResult;

  constructor(message: string, status: number, code?: string,
              retryable?: boolean, result?: ScanResult) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.retryable = retryable;
    this.result = result;
  }
}

/** Phase 23 §2 — a transient SQLite lock-busy answer, by body shape.

    The backend returns HTTP 503 with {status:"busy", level:"amber",
    title:"TEMPORARILY BUSY", detail, retryable:true} plus Retry-After.
    The body carries NO `error` key, so without this check every busy
    answer collapsed into the generic "service temporarily unavailable"
    message and the whole amber contract was discarded. */
function busyError(body: unknown, status: number): ApiError | null {
  if (body === null || typeof body !== "object") return null;
  const b = body as { status?: unknown; level?: unknown; title?: unknown,
                      detail?: unknown; retryable?: unknown };
  if (b.status !== "busy" || b.retryable !== true) return null;
  const result: ScanResult = {
    status: "busy",
    level: b.level === "green" || b.level === "red" ? b.level : "amber",
    title: typeof b.title === "string" && b.title.trim() ? b.title : "TEMPORARILY BUSY",
    detail: typeof b.detail === "string" && b.detail.trim() ? b.detail : undefined,
  };
  return new ApiError(result.detail ?? result.title, status, "busy", true, result);
}

// How long we wait for the backend before giving up. Without this, a phone
// pointed at an unreachable server would hang on a spinner forever.
const REQUEST_TIMEOUT_MS = 20000;

function networkError(timedOut: boolean): ApiError {
  return new ApiError(
    timedOut
      ? "The connection is taking too long. Please check your Wi-Fi connection and try again."
      : "Unable to connect. Please check your Wi-Fi connection or contact the system administrator.",
    0,
  );
}

async function send(url: string, init?: RequestInit): Promise<Response> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    return await fetch(url, {
      ...init,
      signal: controller.signal,
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    });
  } finally {
    clearTimeout(timer);
  }
}

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const baseUrl = await getApiBaseUrl();
  if (baseUrl.length === 0) {
    // Production safety: nothing configured and no development host to
    // discover from. Sanitized message only — no URLs in user UI.
    throw new ApiError(
      "This device is not configured to reach the convocation server. Ask the administrator to set the backend under Admin > Backend Connection.",
      0,
    );
  }
  let response: Response;
  try {
    response = await send(`${baseUrl}${path}`, init);
  } catch (e) {
    const timedOut = e instanceof Error && e.name === "AbortError";
    // Technical diagnostics stay in the developer console only (plain log:
    // Expo Go LogBox floats warn/error banners into the user UI, which must
    // never show raw API errors, base URLs, or IPs). The sanitized
    // ApiError message below is what reaches ErrorState on the device.
    if (__DEV__) {
      console.log(`[api] ${path} request failed:`, { baseUrl, error: e });
    }
    // Stale-URL recovery: in auto mode a changed DHCP lease fails the first
    // attempt; the discovered development host is probed and the request
    // retried once against it. Custom URLs are never auto-replaced.
    const fallback = await noteUnreachableBaseUrl(baseUrl);
    if (fallback) {
      if (__DEV__) {
        console.log(`[api] ${path} retrying on discovered backend:`, fallback);
      }
      try {
        response = await send(`${fallback}${path}`, init);
      } catch (e2) {
        const retryTimedOut = e2 instanceof Error && e2.name === "AbortError";
        if (__DEV__) {
          console.log(`[api] ${path} discovered backend failed too:`, {
            fallback,
            error: e2,
          });
        }
        throw networkError(retryTimedOut);
      }
    } else {
      throw networkError(timedOut);
    }
  }
  let body: unknown = null;
  try {
    body = await response.json();
  } catch {
    body = null;
  }
  if (!response.ok) {
    // Phase 23 §2: contention is recognised BEFORE the generic error path,
    // so the volunteer gets the sanctioned amber retry guidance instead of
    // a red failure and a spurious offline transition.
    const busy = busyError(body, response.status);
    if (busy) throw busy;
    const message =
      body !== null &&
      typeof body === "object" &&
      "error" in body &&
      typeof (body as { error: unknown }).error === "string"
        ? (body as { error: string }).error
        : "The service is temporarily unavailable. Please try again.";
    const code =
      body !== null &&
      typeof body === "object" &&
      "code" in body &&
      typeof (body as { code: unknown }).code === "string"
        ? (body as { code: string }).code
        : undefined;
    throw new ApiError(message, response.status, code);
  }
  return body as T;
}

export async function fetchDashboard(): Promise<DashboardData> {
  return request<DashboardData>("/api/dashboard");
}

/**
 * KPI subset without feed/sync — what Home needs for event progress.
 * Same field contract as DashboardData minus the operations-only arrays.
 */
export async function fetchDashboardSummary(): Promise<DashboardData> {
  return request<DashboardData>("/api/dashboard/summary");
}

/**
 * Authoritative runtime configuration (Phase 35K): event identity,
 * population counts, gate list and shared limits. The app consumes this
 * instead of hard-coded constants; the fallbacks in src/config.ts remain
 * isolated to the startup screens only.
 */
export async function fetchAppConfig(): Promise<AppConfig> {
  return request<AppConfig>("/api/config");
}

/**
 * Announcement audience for the broadcast composer (35K Part I).
 * With gate ids: students currently inside at those gates (real scan
 * history). Without: the all-students roster count. The server response
 * carries a basis string stating the rule.
 */
export async function fetchBroadcastAudience(
  gateIds?: number[],
): Promise<BroadcastAudience> {
  const query =
    gateIds && gateIds.length > 0
      ? `?gates=${gateIds.map((id) => String(id)).join(",")}`
      : "";
  return request<BroadcastAudience>(`/api/broadcast/audience${query}`);
}

export async function fetchGates(): Promise<Gate[]> {
  const data = await request<{ gates: Gate[] }>("/api/gates");
  return data.gates;
}

export async function postScan(input: {
  payload: string;
  gate_id: number;
  mode: ScanMode;
  volunteer: string;
  occasion: Occasion;
}): Promise<ScanResult> {
  const headers = await scannerAuthHeaders();
  return request<ScanResult>("/api/scan", {
    method: "POST",
    body: JSON.stringify(input),
    headers,
  });
}

export async function postSync(
  items: QueuedScan[],
): Promise<{ synced: number; results: { payload: string; result: ScanResult }[] }> {
  const headers = await scannerAuthHeaders();
  return request("/api/sync", {
    method: "POST",
    body: JSON.stringify({ items }),
    headers,
  });
}

// ---------------------------------------------------- scanner auth (P14)
/** Sign in a volunteer scanner and persist the returned session locally. */
export async function loginScanner(
  username: string,
  pin: string,
): Promise<ScannerSession> {
  const data = await request<{
    ok: boolean;
    token: string;
    expires_at: string;
    scanner: { username: string; display_name: string; gates: number[] };
    error?: string;
  }>("/api/scanner/login", {
    method: "POST",
    body: JSON.stringify({ username, pin }),
  });
  const session: ScannerSession = {
    token: data.token,
    expiresAt: data.expires_at,
    username: data.scanner.username,
    displayName: data.scanner.display_name,
    gates: data.scanner.gates,
  };
  await setScannerSession(session);
  return session;
}

/** Sign out the current scanner (best-effort server revoke + local clear). */
export async function logoutScanner(): Promise<void> {
  try {
    const headers = await scannerAuthHeaders();
    await request("/api/scanner/logout", { method: "POST", headers });
  } catch {
    // Revocation is best-effort; the local session is cleared regardless.
  }
  await clearScannerSession();
}

/** Build the X-Scanner-Token header when a live session exists, else {}. */
async function scannerAuthHeaders(): Promise<Record<string, string>> {
  const s = await getScannerSession();
  return s ? { "X-Scanner-Token": s.token } : {};
}

/** Deterministic demo records for the scanner's Test Scan feature. */
export async function fetchTestRecords(): Promise<TestRecord[]> {
  const data = await request<{ records: TestRecord[] }>("/api/test-records");
  return data.records;
}

/** Clear scans recorded by the test records so entry/exit/duplicate
 * scenarios can be re-run. Returns how many scans were removed.
 * Issue 1 (Release blocker): destructive — sends the admin PIN header
 * so the server can verify authorization independently of the client. */
export async function resetTestScans(): Promise<number> {
  const adminPin = await getAdminPin();
  const headers: Record<string, string> = {};
  if (adminPin) headers["X-Admin-Pin"] = adminPin;
  const data = await request<{ ok: boolean; removed: number }>(
    "/api/test-reset",
    { method: "POST", headers },
  );
  return data.removed;
}

export async function fetchGuests(): Promise<Guest[]> {
  // Phase 26C: the roster carries phone PII, so it rides the scanner
  // session like /api/scan. Anonymous callers get a 401 → sign-in prompt.
  const data = await request<{ guests: Guest[] }>("/api/guests", {
    headers: await scannerAuthHeaders(),
  });
  return data.guests;
}

export async function registerGuest(input: {
  name: string;
  phone: string;
  host_roll_no: string;
}): Promise<GuestRegistration> {
  const data = await request<GuestRegistration>("/api/guests", {
    method: "POST",
    body: JSON.stringify(input),
  });
  if (!data.ok) {
    throw new ApiError(data.error ?? "Guest registration failed.", 400);
  }
  return data;
}

export async function fetchGuestPass(gid: number): Promise<GuestPass> {
  // Phase 27 C3: the pass payload is a bearer credential, so reading one
  // rides the scanner session like the roster — an anonymous caller gets 401
  // instead of minting a pass from an enumerable gid. Mobile registration
  // always runs signed-in; API/kiosk registrants read their own pass back
  // with the print_token the POST response issued.
  const data = await request<GuestPass & { ok: boolean; error?: string }>(
    `/api/guest-pass/${gid}`,
    { headers: await scannerAuthHeaders() },
  );
  if (!data.ok) {
    throw new ApiError(data.error ?? "Guest pass not found.", 404);
  }
  return data;
}

export async function fetchBroadcasts(): Promise<BroadcastEntry[]> {
  const data = await request<{ log: BroadcastEntry[] }>("/api/broadcasts");
  return data.log;
}

export async function sendBroadcast(input: {
  audience: string;
  message: string;
  sent_by: string;
}): Promise<BroadcastResponse> {
  // Administrator PIN from the on-device gate (Phase 35G): the backend
  // rejects broadcast POSTs that arrive without the X-Admin-Pin header.
  const adminPin = await getAdminPin();
  const data = await request<BroadcastResponse>("/api/broadcasts", {
    method: "POST",
    headers: adminPin ? { "X-Admin-Pin": adminPin } : undefined,
    body: JSON.stringify(input),
  });
  if (!data.ok) {
    throw new ApiError(data.error ?? "Broadcast failed.", 400);
  }
  return data;
}

/**
 * Administrator PIN check (Phase 35G). Called once by the mobile admin
 * gate; the PIN is kept in AsyncStorage on the device and attached to
 * subsequent admin POSTs via the X-Admin-Pin header.
 */
export async function verifyAdminPin(pin: string): Promise<{ ok: boolean }> {
  return request<{ ok: boolean }>("/api/admin/verify", {
    method: "POST",
    body: JSON.stringify({ pin }),
  });
}

/** Pakistani mobile numbers: 03XXXXXXXXX, with optional leading zero and separators. */
export function isValidPhone(phone: string): boolean {
  const digits = phone.replace(/[\s\-()]/g, "");
  return /^0?3\d{9}$/.test(digits);
}

// --------------------------------------------------------------- search
// Attendee/guest lookup for the Search destination (spec §12: recovery for
// damaged QR codes, no QR, or camera failure). Backend endpoint is the
// additive GET /api/search added in Phase 34 (audit: it did not exist).

export interface SearchResult {
  type: "student" | "guest";
  name: string;
  roll_no?: string;
  program?: string;
  gender?: string;
  /** Guest only: integer id for /api/guest-pass/<gid> navigation. */
  gid?: number;
  host_roll_no?: string;
  /** Guest only: host student's roster name when known. */
  host_name?: string | null;
  phone?: string;
  /** Guest only: lifecycle state "active" | "revoked" (Phase 34 Part C). */
  status?: string;
  /** Student: latest scan is an entry. Guest: any scan exists (single-use). */
  inside: boolean;
  /** Guest only: the pass has already been used. */
  used: boolean;
  /** Last scan context when inside/used (gate label + time), else null. */
  last_scan: { gate: string; time: string; mode: string } | null;
}

export async function searchAttendees(query: string): Promise<SearchResult[]> {
  const q = query.trim();
  if (q.length < 2) {
    return [];
  }
  // Phase 34 (Part D): the lookup carries guest phone PII and once exposed
  // the qr_id credential, so it rides the scanner session like /api/scan —
  // an anonymous caller gets 401 (surfaced as a sign-in prompt).
  const data = await request<{ results: SearchResult[] }>(
    `/api/search?q=${encodeURIComponent(q)}`,
    { headers: await scannerAuthHeaders() },
  );
  return data.results;
}
