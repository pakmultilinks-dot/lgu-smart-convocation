// Typed client for the LGU Smart Convocation Flask backend.
// The base URL is read from settings on every call so the Settings screen
// can change it without an app restart. QR payloads are opaque strings;
// all verification happens server side, nothing secret lives in this bundle.

import { getApiBaseUrl } from "../store/settings";
import type { QueuedScan } from "../store/offlineQueue";

export interface Gate {
  id: number;
  code: string;
  label: string;
}

export type ScanMode = "entry" | "exit";
export type ScanLevel = "green" | "red" | "amber";

export interface ScanResult {
  status: "ok" | "error";
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
  expected_total: number;
  expected_male: number;
  expected_female: number;
  expected_guests: number;
  inside_total: number;
  male: number;
  female: number;
  guests_inside: number;
  arrival_pct: number;
  busiest_gate: string;
  throughput: { gate: Gate; count: number }[];
  sync: { gate: Gate; last: string | null; count: number }[];
  feed: FeedItem[];
  generated_at: string;
}

export interface DemoPayload {
  payload: string | null;
  hint: string;
}

export interface Guest {
  id: number;
  name: string;
  phone: string;
  host_roll_no: string;
  qr_id: string;
  used: boolean;
  created_at: string;
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
  used: boolean;
  payload: string;
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

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

// How long we wait for the backend before giving up. Without this, a phone
// pointed at an unreachable server would hang on a spinner forever.
const REQUEST_TIMEOUT_MS = 20000;

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const baseUrl = await getApiBaseUrl();
  const url = `${baseUrl}${path}`;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  let response: Response;
  try {
    response = await fetch(url, {
      ...init,
      signal: controller.signal,
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    });
  } catch (e) {
    const timedOut = e instanceof Error && e.name === "AbortError";
    throw new ApiError(
      timedOut
        ? `The server at ${baseUrl} took too long to respond. Check the API base URL in Settings.`
        : `Could not reach the server at ${baseUrl}. Check the API base URL in Settings.`,
      0,
    );
  } finally {
    clearTimeout(timer);
  }
  let body: unknown = null;
  try {
    body = await response.json();
  } catch {
    body = null;
  }
  if (!response.ok) {
    const message =
      body !== null &&
      typeof body === "object" &&
      "error" in body &&
      typeof (body as { error: unknown }).error === "string"
        ? (body as { error: string }).error
        : `Server returned status ${response.status}.`;
    throw new ApiError(message, response.status);
  }
  return body as T;
}

export async function fetchDashboard(): Promise<DashboardData> {
  return request<DashboardData>("/api/dashboard");
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
}): Promise<ScanResult> {
  return request<ScanResult>("/api/scan", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export async function postSync(
  items: QueuedScan[],
): Promise<{ synced: number; results: { payload: string; result: ScanResult }[] }> {
  return request("/api/sync", {
    method: "POST",
    body: JSON.stringify({ items }),
  });
}

export async function fetchDemoPayload(): Promise<DemoPayload> {
  return request<DemoPayload>("/api/demo-payload");
}

export async function fetchGuests(): Promise<Guest[]> {
  const data = await request<{ guests: Guest[] }>("/api/guests");
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
  const data = await request<GuestPass & { ok: boolean; error?: string }>(
    `/api/guest-pass/${gid}`,
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
  const data = await request<BroadcastResponse>("/api/broadcasts", {
    method: "POST",
    body: JSON.stringify(input),
  });
  if (!data.ok) {
    throw new ApiError(data.error ?? "Broadcast failed.", 400);
  }
  return data;
}

/** Pakistani mobile numbers: 03XXXXXXXXX, with optional leading zero and separators. */
export function isValidPhone(phone: string): boolean {
  const digits = phone.replace(/[\s\-()]/g, "");
  return /^0?3\d{9}$/.test(digits);
}
