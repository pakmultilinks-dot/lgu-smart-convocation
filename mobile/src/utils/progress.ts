// Safe progress math shared by every bar and percentage in the app
// (Phase 35A bugs 1, 2, 5). value/max in → 0..100 percent out; 0 means
// empty; max <= 0 or non-finite input never produce NaN/Infinity.

/** Clamp a raw percentage into a safe 0..100 band. */
export function safePercentFromPct(pct: number): number {
  if (!Number.isFinite(pct)) return 0;
  return Math.max(0, Math.min(100, pct));
}

/** value / max as a safe 0..100 percent. max <= 0 → 0 (empty, no divide-by-zero). */
export function safePercent(value: number, max: number): number {
  if (!Number.isFinite(value) || !Number.isFinite(max) || max <= 0) return 0;
  return safePercentFromPct((value / max) * 100);
}

/**
 * Progress denominator (Phase 35K Part B): ONLY the admin-configured
 * expected attendance is a denominator. A student roster count is a
 * different concept (registrations) and must never silently substitute as
 * the event target — when the target is unset (<= 0), callers render an
 * explicit "Expected attendance not set" state instead of a bar.
 */
export function progressDenominator(attendance: number): number {
  if (Number.isFinite(attendance) && attendance > 0) return attendance;
  return 0;
}
