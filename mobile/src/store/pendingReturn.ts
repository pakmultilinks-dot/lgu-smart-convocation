/**
 * Destination interrupted by a signed-out redirect (welcome). Each
 * student screen records where the user was going BEFORE it replaces to
 * welcome; StudentWelcome/login consume it once to seed `returnTo`, so
 * sign-in returns to the original screen instead of Home. Stores full
 * hrefs including query (e.g. "/(student)/support-detail?id=3").
 * Module state only — a reload restarts the flow.
 */
let pending: string | null = null;

export function rememberPendingReturn(path: string): void {
  pending = path;
}

/** Non-destructive read — safe during render (StrictMode double-render
 * would otherwise consume the value on the discarded pass). */
export function peekPendingReturn(): string | null {
  return pending;
}

export function takePendingReturn(): string | null {
  const value = pending;
  pending = null;
  return value;
}