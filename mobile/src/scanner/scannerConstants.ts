// Scanner tuning constants — values preserved verbatim from the proven
// Phase 30 scanner (verified on-device: auto-zoom follow, duplicate
// suppression, result timing). Behavior must not drift during decomposition.

export const RESULT_DISMISS_MS = 4000;
export const SCAN_RELEASE_MS = 1200;
export const ZOOM_MAX = 0.45;
export const ZOOM_STEP = 0.025;
export const ZOOM_TICK_MS = 80;
export const QR_LEAVE_MS = 1400;
export const FRACTION_COMFORT = 0.42;
export const FRAME_DEDUPE_MS = 4000;
export const DIM_COLOR = "rgba(9, 18, 14, 0.55)";
export const FRAME = 260;

/** Local timestamp for queued scans: "YYYY-MM-DD HH:MM:SS" (Asia/Karachi). */
export function localTimestamp(): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Karachi",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(new Date());
}
