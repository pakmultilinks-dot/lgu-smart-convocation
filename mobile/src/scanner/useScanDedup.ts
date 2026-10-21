import { useCallback, useRef } from "react";
import { FRAME_DEDUPE_MS, SCAN_RELEASE_MS } from "./scannerConstants";
import { shouldSuppressRepeat, type CooldownEntry } from "./scanCooldown";

/**
 * In-frame duplicate suppression (spec §22) + one-scan-at-a-time gate.
 * `claim` returns false when the scan must be ignored; `release` re-opens
 * the gate shortly after the round trip so rapid double-fires stay quiet.
 *
 * Phase 35K (Part P): the cooldown key is payload + mode + gate — an
 * Entry→Exit sequence for the same pass is two legitimate opposite scans
 * and must never be suppressed. Phase 29: the OCCASION joins the key — the
 * same pass admitted for the rehearsal and then for the main convocation
 * are likewise two legitimate scans. The suppression rule itself lives in
 * scanCooldown.ts (pure, unit-tested).
 */
export function useScanDedup() {
  const scanningRef = useRef(false);
  const lastRef = useRef<CooldownEntry | null>(null);

  const claim = useCallback(
    (
      payload: string,
      mode: string,
      gateId: number | null,
      occasion: string,
    ): boolean => {
      if (scanningRef.current || !payload) return false;
      if (
        shouldSuppressRepeat(
          lastRef.current,
          payload,
          mode,
          gateId,
          occasion,
          Date.now(),
          FRAME_DEDUPE_MS,
        )
      ) {
        return false;
      }
      lastRef.current = { payload, mode, gateId, occasion, at: Date.now() };
      scanningRef.current = true;
      return true;
    },
    [],
  );

  const release = useCallback(() => {
    setTimeout(() => {
      scanningRef.current = false;
    }, SCAN_RELEASE_MS);
  }, []);

  return { claim, release };
}
