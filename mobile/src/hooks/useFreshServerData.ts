// Controlled server-data freshness for student screens (Phase 8).
//
// One shared rule for every screen that shows server truth: fetch when the
// screen opens, refetch when the student returns to it, refresh after the
// app resumes from the background, allow a manual refresh, and keep a
// periodic refresh no slower than 30s — but ONLY while the screen is
// focused AND the app is foregrounded. No WebSockets, no push, no new
// dependencies: AppState + one interval + focus lifecycle.
//
// Overlap safety: a tick that fires while a refresh is already in flight
// is skipped (the in-flight request is the fresher one) — never two
// concurrent requests for the same screen, never duplicate timers (the
// single interval ref is stopped on blur/background and restarted on
// focus/resume). A failed refresh is retried by the next tick; screens
// keep their last data and own their error/stale presentation, so a
// network failure is never rendered as an authoritative rejection.

import { useFocusEffect } from "expo-router";
import { useCallback, useEffect, useRef } from "react";
import { AppState, type AppStateStatus } from "react-native";

/** Foreground freshness cadence for data that must stay current. */
export const STUDENT_REFRESH_MS = 20000;

/**
 * Wire a screen's `load` function to the freshness lifecycle.
 *
 * Returns a stable `refresh()` for manual refresh actions — coalesced with
 * whatever the poll/focus cycle is doing (an in-flight refresh absorbs the
 * press instead of spawning a duplicate request).
 */
export function useFreshServerData(
  refresh: () => Promise<void>,
  intervalMs: number = STUDENT_REFRESH_MS,
): () => Promise<void> {
  const refreshRef = useRef(refresh);
  const runningRef = useRef(false);
  const focusedRef = useRef(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Always call the latest closure (filters, state) — synced in an effect,
  // never during render (react-hooks/refs).
  useEffect(() => {
    refreshRef.current = refresh;
  }, [refresh]);

  const run = useCallback(async () => {
    // Never background traffic, never overlapping requests: a tick while a
    // refresh is in flight or the app is not foregrounded is simply lost —
    // the next tick (or focus/resume) fetches again.
    if (runningRef.current || AppState.currentState !== "active") return;
    runningRef.current = true;
    try {
      await refreshRef.current();
    } catch {
      // Screens handle their own errors (they set error/stale state from
      // inside load). A rejection here is a failed poll, not a verdict —
      // the next tick retries.
    } finally {
      runningRef.current = false;
    }
  }, []);

  const stopPolling = useCallback(() => {
    if (pollRef.current !== null) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const startPolling = useCallback(() => {
    stopPolling(); // single timer — restart never duplicates
    pollRef.current = setInterval(() => {
      if (focusedRef.current) void run();
    }, intervalMs);
  }, [intervalMs, run, stopPolling]);

  // Screen open / return to screen: fetch now, poll while focused, stop on
  // blur (navigation away or unmount).
  useFocusEffect(
    useCallback(() => {
      focusedRef.current = true;
      void run();
      startPolling();
      return () => {
        focusedRef.current = false;
        stopPolling();
      };
    }, [run, startPolling, stopPolling]),
  );

  // Resume from background: fetch immediately and restart the cadence.
  // Backgrounded/inactive: stop the cadence (no polling while hidden).
  useEffect(() => {
    const sub = AppState.addEventListener("change", (state: AppStateStatus) => {
      if (state === "active") {
        if (focusedRef.current) {
          void run();
          startPolling();
        }
      } else {
        stopPolling();
      }
    });
    return () => {
      sub.remove();
      stopPolling();
    };
  }, [run, startPolling, stopPolling]);

  return run;
}
