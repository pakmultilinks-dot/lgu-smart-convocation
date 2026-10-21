/**
 * Administrator PIN lockout (Phase 35H item 23). Pure, clock-injected
 * state — unit-testable without React or AsyncStorage: 3 consecutive
 * wrong PINs lock the gate for 30 seconds; a correct PIN resets the
 * counters, and an expired lock grants a fresh 3-attempt allowance
 * (the penalty window already separated the old strikes). Wrong-PIN
 * rejections (backend 401 / ok:false) count toward the lockout —
 * network errors never reached the verifier and do NOT.
 */

export const MAX_ATTEMPTS = 3;
export const LOCKOUT_MS = 30000;

export interface AdminLockState {
  /** Consecutive wrong-PIN attempts since the last success. */
  attempts: number;
  /** Epoch ms until which attempts are blocked; 0 = not locked. */
  lockUntil: number;
}

export const initialLockState: AdminLockState = { attempts: 0, lockUntil: 0 };

/** Remaining lockout ms at `now` (0 = unlocked). */
export function lockRemainingMs(state: AdminLockState, now: number): number {
  return state.lockUntil > now ? state.lockUntil - now : 0;
}

export function isLocked(state: AdminLockState, now: number): boolean {
  return lockRemainingMs(state, now) > 0;
}

/** Count a wrong PIN. Locks for LOCKOUT_MS once MAX_ATTEMPTS is hit. */
export function registerFailure(
  state: AdminLockState,
  now: number,
): AdminLockState {
  if (isLocked(state, now)) return state;
  // An expired lock (lockUntil set, now past it) restarts the allowance.
  const base = state.lockUntil > 0 ? initialLockState : state;
  const attempts = base.attempts + 1;
  if (attempts >= MAX_ATTEMPTS) {
    return { attempts, lockUntil: now + LOCKOUT_MS };
  }
  return { attempts, lockUntil: 0 };
}

/** Correct PIN — clear the counters (also used after a successful unlock). */
export function resetOnSuccess(): AdminLockState {
  return { attempts: 0, lockUntil: 0 };
}

/** Whole seconds remaining, rounded up — the countdown display. */
export function lockSecondsRemaining(
  state: AdminLockState,
  now: number,
): number {
  return Math.ceil(lockRemainingMs(state, now) / 1000);
}
