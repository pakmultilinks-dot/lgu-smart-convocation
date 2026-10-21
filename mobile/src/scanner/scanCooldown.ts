// Camera double-read cooldown (Phase 35K Part P). Pure logic — zero
// app/RN imports — extracted from useScanDedup so the mode+gate-aware
// behaviour is unit-tested directly (scripts/scanner-logic-test.mjs).
//
// The same QR payload seen twice within the window is ONE camera read, not
// two scans — but only when the mode, gate and OCCASION are unchanged. An
// Entry→Exit sequence for the same pass is two legitimate, opposite scans
// and must never be suppressed; likewise the same pass checked in for the
// rehearsal and later for the main convocation (Phase 29), or the same
// pass at two different gates.

export interface CooldownEntry {
  payload: string;
  mode: string;
  gateId: number | null;
  occasion: string;
  at: number;
}

/**
 * True when the new read must be suppressed as a camera double-read.
 * Suppression requires ALL of: same payload, same mode, same gate, same
 * occasion and within the cooldown window. A different mode (Entry vs
 * Exit), a different gate or a different occasion always passes through.
 */
export function shouldSuppressRepeat(
  last: CooldownEntry | null,
  payload: string,
  mode: string,
  gateId: number | null,
  occasion: string,
  now: number,
  windowMs: number,
): boolean {
  if (!payload) return true; // nothing scanned → treat as suppressed
  if (!last) return false;
  return (
    last.payload === payload &&
    last.mode === mode &&
    last.gateId === gateId &&
    last.occasion === occasion &&
    now - last.at < windowMs
  );
}
