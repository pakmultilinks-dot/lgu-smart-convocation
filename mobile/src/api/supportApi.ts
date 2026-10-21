// Typed student support API (Phase 9): open a request and read its
// history. All auth rides the shared request helper (status + server code
// surfaced through ApiError) with the Bearer token from studentSession.
// A request never mutates a registration — corrections are applied by the
// Examination Department, which this screen can only ask about.

import { request } from "./client";

const BASE = "/api/student/support";

export type Category =
  | "missing_registration"
  | "correction"
  | "cancellation"
  | "account_claim"
  | "general";

export const CATEGORIES: { value: Category; label: string; hint: string }[] = [
  {
    value: "missing_registration",
    label: "Missing / mismatched",
    hint: "My registration number is missing or does not match my record.",
  },
  {
    value: "correction",
    label: "Correct details",
    hint: "My name, roll number or department needs correcting.",
  },
  {
    value: "cancellation",
    label: "Cancellation",
    hint: "A cancellation or reinstatement needs review.",
  },
  {
    value: "account_claim",
    label: "Account claim",
    hint: "I cannot claim my registration, or my account is already taken.",
  },
  { value: "general", label: "Question", hint: "A general convocation question." },
];

export type SupportStatus =
  | "submitted"
  | "under_review"
  | "info_required"
  | "resolved"
  | "rejected";

export interface SupportResponse {
  body: string;
  at: string;
}

export interface SupportRequest {
  id: number;
  reference: string;
  category: Category;
  category_label: string;
  subject: string;
  message: string;
  status: SupportStatus;
  status_label: string;
  created_at: string;
  updated_at: string;
  resolved_at: string | null;
  latest_response: SupportResponse | null;
}

export interface SupportEvent {
  action: string;
  actor_role: "student" | "staff";
  body: string;
  at: string;
  before_status: string;
  after_status: string;
}

export interface SupportList {
  convocation: { name: string; year: string } | null;
  total: number;
  requests: SupportRequest[];
}

export interface SupportDetail {
  ok: boolean;
  request: SupportRequest & { history: SupportEvent[] };
}

function auth(token: string): Record<string, string> {
  return { Authorization: `Bearer ${token}` };
}

export function create(
  token: string,
  input: { category: Category; subject: string; message: string },
): Promise<{ ok: boolean; request: SupportRequest }> {
  return request(`${BASE}`, {
    method: "POST",
    headers: auth(token),
    body: JSON.stringify(input),
  });
}

export function list(token: string): Promise<SupportList> {
  return request<SupportList>(BASE, { headers: auth(token) });
}

export function detail(token: string, id: number): Promise<SupportDetail> {
  return request<SupportDetail>(`${BASE}/${id}`, { headers: auth(token) });
}

/** Status pill state — mirrors the web badge mapping so the app and portal
 *  read the same. Staff-only statuses collapse to neutral. */
export function pillState(status: SupportStatus): "accept" | "queued" | "info" | "invalid" {
  if (status === "resolved") return "accept";
  if (status === "rejected") return "invalid";
  if (status === "info_required") return "info";
  return "queued";
}
