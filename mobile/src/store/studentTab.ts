import type { Href } from "expo-router";

/**
 * Last focused student tab (Phase 31 back contract). Detail screens
 * (profile, event, readiness, support, history, medalists) are hidden
 * tab screens reached from a visible tab; their Back must return to the
 * tab that opened them, not a hardcoded one. Each visible tab records
 * itself on focus; detail screens read it with a per-screen fallback.
 * Module state only — no persistence needed (a reload restarts the flow).
 */
let lastTab: Href | null = null;

export function rememberStudentTab(tab: Href): void {
  lastTab = tab;
}

export function lastStudentTab(fallback: Href): Href {
  return lastTab ?? fallback;
}