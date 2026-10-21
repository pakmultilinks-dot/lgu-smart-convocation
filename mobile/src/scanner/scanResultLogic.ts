// Pure scanner logic (Phase 35B): scan-result classification, the
// race-safe result timeline (1.2s auto-return), volunteer-name
// persistence and the scan payload stamp. Zero app/RN imports —
// compiles standalone and is unit-tested directly
// (scripts/scanner-logic-test.mjs) via project tsc.

/** "entry" | "exit" — structurally identical to client ScanMode. */
export type ScanMode = "entry" | "exit";

/** Structural scan result — compatible with client ScanResult. */
export interface ScanResultLike {
  // "busy" is a bounded retryable contention answer (Phase 22 §3), never an
  // outcome — it must not classify as valid, already-used or invalid.
  status: "ok" | "error" | "busy";
  level: "green" | "red" | "amber";
  title: string;
  detail?: string;
  name?: string;
  sub?: string;
  gate?: string;
  time?: string;
}

/** Scan results auto-return to the camera after ~1.2s (Part E). */
export const SCAN_RESULT_MS = 1200;

export type ScanOutcomeKind = "valid" | "already-used" | "invalid" | "other";
export type HapticCue = "success" | "warning" | "error";

export interface ClassifiedScan {
  kind: ScanOutcomeKind;
  /** Canonical state title shown to the volunteer. */
  stateTitle: string;
  /** Entry / Exit wording derived from the result title, when present. */
  action?: "Entry" | "Exit";
  haptic: HapticCue;
}

/** Developer/infra text must never reach the operator. `fallback` lets the
    busy path use its own sanctioned wording instead of "Scan failed". */
function sanitizeTitle(title: string, fallback = "Scan failed"): string {
  const t = (title ?? "").trim();
  if (
    !t ||
    /https?:\/\//i.test(t) ||
    /traceback|exception|stack ?trace|<html/i.test(t)
  ) {
    return fallback;
  }
  return t;
}

/**
 * Gate-required rule (Phase 35J PART G): a scan may never leave the
 * device without a valid gate — the payload, offline queue and backend
 * POST all depend on a selected gate id. Pure type predicate so the
 * ScannerScreen cannot drift back to a default gate; unit-tested.
 */
export function scanGateBlocked(gateId: number | null): gateId is null {
  return gateId === null;
}

/**
 * Gate-chip label for the scanner top bar (Scanner Fix Round 1).
 * Once gates have LOADED, the chip can never read "Loading gates...":
 * a selected gate shows its server-provided name, no selection shows
 * the sanctioned prompt "Choose a gate" (the gate sheet's own words),
 * and a load error shows "Gate unavailable". "Loading gates..." is
 * reserved for the genuine pre-load state. Pure + unit-tested
 * (scripts/scanner-logic-test.mjs).
 */
export function resolveGateLabel(
  gates: readonly { id: number; label: string }[],
  gateId: number | null,
  gatesError: string | null,
  gatesLoaded: boolean,
): string {
  const selected = gates.find((g) => g.id === gateId);
  if (selected) return selected.label;
  if (gatesError) return "Gate unavailable";
  return gatesLoaded ? "Choose a gate" : "Loading gates...";
}

/**
 * Sanitize a backend detail string for the operator (Phase 35J PART H):
 * technical phrases (signature, tamper, API, backend, HTTP, traceback…)
 * are replaced with the sanctioned instruction. Anything that reads as
 * operational English passes through unchanged.
 */
export function sanitizeInvalidDetail(detail?: string): string | undefined {
  const text = (detail ?? "").trim();
  if (!text) return undefined;
  if (
    /signature|tamper|forged?|api|backend|https?:\/\//i.test(text) ||
    /traceback|exception|stack ?trace|error 5\d\d/i.test(text)
  ) {
    return undefined;
  }
  return text;
}

/**
 * Volunteer identity validation (Phase 35L F): a usable name needs at
 * least 2 letters — empty, whitespace-only and single-character values
 * are rejected; normal names with spaces are fine. Pure + unit-tested.
 */
export function isValidVolunteerName(value: string): boolean {
  const letters = (value ?? "").replace(/[^A-Za-z]/g, "");
  return letters.length >= 2;
}

/**
 * Map a backend ScanResult to the volunteer-facing state:
 * - VALID             — recorded scan (ok + green)
 * - ALREADY USED      — previously used pass / already inside
 * - INVALID           — unknown or forged code ("Invalid code")
 * - other             — setup/queue/sync notices (kept with backend text)
 */
export function classifyScanResult(r: ScanResultLike): ClassifiedScan {
  // Phase 23 §2: transient SQLite contention is a PROMPT-AND-RETRY notice,
  // never a gate outcome. Checked FIRST so a busy answer can never fall into
  // the valid / already-used / invalid branches, and always carrying the
  // warning (not error) haptic so a busy database never reads to the
  // volunteer as a broken scan. Uses the RAW title deliberately: the
  // sanitizeTitle fallback below would otherwise substitute its own
  // "Scan failed" wording for an empty busy title.
  if (r.status === "busy") {
    const busyTitle = sanitizeTitle(r.title ?? "", "TEMPORARILY BUSY")
      .toUpperCase();
    return {
      kind: "other",
      stateTitle: busyTitle || "TEMPORARILY BUSY",
      haptic: "warning",
    };
  }
  const title = sanitizeTitle(r.title ?? "");
  const upper = title.toUpperCase();
  if (r.status === "ok" && r.level === "green") {
    // 35L (D): a guest scan resolves into its own success state — the
    // identity line carries the host relationship ("Guest of …").
    // Phase 29: a rehearsal check-in is its own success state so the
    // volunteer never mistakes it for main-ceremony admission.
    return {
      kind: "valid",
      stateTitle: upper.includes("REHEARSAL")
        ? "Rehearsal entry"
        : upper.includes("GUEST")
          ? "Guest entry"
          : "VALID",
      action: upper.includes("EXIT") ? "Exit" : "Entry",
      haptic: "success",
    };
  }
  if (r.status === "error" && upper.includes("ALREADY")) {
    // Phase 35K (O): "ALREADY SYNCED" is a queue-reconciliation notice, not
    // a gate-identity outcome — it must not render as the full-surface
    // "Already used" state. It falls through to kind "other" (compact
    // notice card) after the ALREADY SYNCED check below.
    if (upper !== "ALREADY SYNCED") {
      return { kind: "already-used", stateTitle: "Already used", haptic: "error" };
    }
  }
  if (r.status === "error" && r.level === "red") {
    if (upper === "UNKNOWN CODE" || upper === "INVALID CODE") {
      // 35J (H): both invalid outcomes share the mandated main message
      // "Invalid code"; the operator instruction is added at render time.
      return {
        kind: "invalid",
        stateTitle: "Invalid code",
        haptic: "error",
      };
    }
  }
  return {
    kind: "other",
    stateTitle: title || "Scan result",
    haptic: r.level === "amber" ? "warning" : "error",
  };
}

/** Injectable timers so the lifecycle is unit-testable. */
export interface ResultTimers {
  set(fn: () => void, ms: number): unknown;
  clear(handle: unknown): void;
}

export interface ScanResultController {
  show(result: ScanResultLike, ms: number): void;
  clear(): void;
  dispose(): void;
}

/**
 * Race-safe result timeline: a new result cancels the previous timer
 * (no overlapping timers), a stale timer can never clear a newer result
 * (sequence token), and dispose() kills pending timers on unmount
 * (no setState after unmount).
 */
export function createScanResultController(
  onShow: (r: ScanResultLike) => void,
  onClear: () => void,
  timers: ResultTimers = {
    set: (fn, ms) => setTimeout(fn, ms),
    clear: (h) => clearTimeout(h as ReturnType<typeof setTimeout>),
  },
): ScanResultController {
  let timer: unknown = null;
  let seq = 0;
  const clearPending = () => {
    if (timer !== null) {
      timers.clear(timer);
      timer = null;
    }
  };
  return {
    show(result, ms) {
      clearPending();
      const mine = ++seq;
      onShow(result);
      timer = timers.set(() => {
        if (mine === seq) {
          timer = null;
          onClear();
        }
      }, ms);
    },
    clear() {
      seq += 1;
      clearPending();
      onClear();
    },
    dispose() {
      seq += 1;
      clearPending();
    },
  };
}

/** Persistence boundary for the volunteer name (AsyncStorage in the app). */
export interface VolunteerStore {
  load(): Promise<string>;
  save(name: string): Promise<void>;
}

/**
 * Volunteer name asked ONCE and persisted (Part C): Scanner loads the
 * stored value on mount/focus, the first-use prompt appears only while
 * nothing is stored, and every scan stamps the stored name.
 */
export function createVolunteerName(store: VolunteerStore) {
  let cached = "";
  return {
    async load(): Promise<string> {
      try {
        cached = (await store.load()).trim();
      } catch {
        cached = "";
      }
      return cached;
    },
    get current(): string {
      return cached;
    },
    get needsSetup(): boolean {
      // 35L (F): a stored name that fails validation is treated as
      // missing — the setup step re-appears instead of scanning under
      // an unusable identity.
      return !isValidVolunteerName(cached);
    },
    async ensure(name: string): Promise<string> {
      const value = name.trim();
      // 35L (F): only a usable name (≥2 letters) is ever persisted —
      // an invalid value never replaces a stored identity.
      if (!isValidVolunteerName(value)) return cached;
      await store.save(value);
      cached = value;
      return value;
    },
  };
}

/** Scan payload stamped with the persisted volunteer name + occasion. */
export function scanPayload(input: {
  volunteerName: string;
  gateId: number;
  mode: ScanMode;
  payload: string;
  occasion: "rehearsal" | "ceremony";
}): {
  gate_id: number;
  mode: ScanMode;
  payload: string;
  volunteer: string;
  occasion: "rehearsal" | "ceremony";
} {
  return {
    gate_id: input.gateId,
    mode: input.mode,
    payload: input.payload,
    volunteer: input.volunteerName.trim() || "Volunteer",
    occasion: input.occasion,
  };
}
