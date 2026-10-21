// Typed readiness API (Phase 10): the personalized convocation readiness
// checklist and reminders. Everything here is server-computed from
// authoritative records — this client never stores or edits registration
// status, event dates or support status locally. It fetches the current
// response and reports the student's read/dismiss intent back to the server,
// which re-validates it before persisting.

import { request } from "./client";

const BASE = "/api/student/readiness";

export type ItemKind = "required" | "info";
export type ItemStatus = "todo" | "done" | "attention";

export interface NavAction {
  label: string;
  route: string;
}

export interface ChecklistItem {
  key: string;
  kind: ItemKind;
  status: ItemStatus;
  title: string;
  detail: string;
  action: NavAction | null;
  source: string;
  at: string | null;
}

export type ReminderPriority = "high" | "normal";
export type ReminderState = "new" | "read" | "dismissed";

export interface Reminder {
  key: string;
  priority: ReminderPriority;
  title: string;
  reason: string;
  at: string | null;
  action: NavAction;
  dismissible: boolean;
  state: ReminderState;
}

export interface ReadinessSummary {
  required_total: number;
  required_done: number;
  percent: number;
  outstanding: number;
  reminders_new: number;
}

export interface Readiness {
  convocation: { name: string; year: string } | null;
  generated_at: string;
  summary: ReadinessSummary;
  items: ChecklistItem[];
  reminders: Reminder[];
}

export interface ReadinessResponse {
  ok: boolean;
  readiness: Readiness;
}

function auth(token: string): Record<string, string> {
  return { Authorization: `Bearer ${token}` };
}

export function get(token: string): Promise<ReadinessResponse> {
  return request<ReadinessResponse>(BASE, { headers: auth(token) });
}

export function mark(
  token: string,
  key: string,
  action: "read" | "dismiss",
): Promise<{ ok: boolean; key: string; state: ReminderState }> {
  return request(`${BASE}/reminders`, {
    method: "POST",
    headers: auth(token),
    body: JSON.stringify({ key, action }),
  });
}

/** Map a backend route string to something the router can push. Routes the
 *  server names are always internal student paths; anything unrecognized
 *  falls back to home so a stray value can never navigate off-app. */
export function routeOf(action: NavAction | null): string {
  if (!action || !action.route) return "/(student)/home";
  return action.route;
}
