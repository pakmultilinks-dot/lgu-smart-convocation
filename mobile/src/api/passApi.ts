// Typed convocation pass + history API (Phase 11; QR issuance Phase 12). The
// pass is a backend-computed invitation derived from the claimed registration,
// its status, open support requests and the published event — this client only
// renders it and never stores or edits eligibility. GET /pass stays a read-only
// invitation (no QR payload). While the invitation state is `eligible`, the
// student may POST to issue a scannable convocation QR: the response carries a
// high-entropy bearer payload the gate verifies server-side against the
// registration ledger (registrations are not linked to the operational roster,
// so the legacy scanner path is separate). The QR carries no personal data.
// History is a read-only ledger of the convocations this student's verified
// records touch.

import { request } from "./client";
import type { OccasionInfo } from "./eventApi";

const PASS = "/api/student/pass";
const HISTORY = "/api/student/history";

export type PassState =
  | "no_convocation"
  | "registration_missing"
  | "registration_cancelled"
  | "registration_revoked"
  | "pending_review"
  | "event_unpublished"
  | "eligible";

export interface PassConvocation {
  id: number;
  name: string;
  year: string;
}

export interface PassRegistration {
  status: string;
  student_name: string;
  registration_number: string;
  roll_number: string;
  department: string;
}

export interface PassEvent {
  name: string;
  year: string;
  date_state: "not_announced" | "expected" | "confirmed";
  date_state_label: string;
  confirmed_date: string | null;
  expected_date: string | null;
  ceremony_time: string | null;
  venue: string;
  rehearsal: { date: string; time: string | null; venue: string } | null;
  instructions: string;
  published_at: string;
  /** Phase 29: the two occasions of the annual cycle, when published. */
  occasions?: OccasionInfo[];
  portal_tz?: string;
}

export interface Pass {
  state: PassState;
  state_label: string;
  title: string;
  detail: string;
  convocation: PassConvocation | null;
  registration: PassRegistration | null;
  event: PassEvent | null;
  qr_available: false;
  qr: null;
  qr_blocker: string;
}

export interface PassResponse {
  ok: boolean;
  pass: Pass;
}

/** The scannable convocation QR minted by POST /pass/issue (Phase 12). */
export interface IssuedPass {
  pass_id: number;
  /** Version-prefixed bearer payload ("LGU2:...") — render as the QR value. */
  payload: string;
  issued_at: string;
  expires_at: string | null;
  convocation: PassConvocation;
  registration: PassRegistration;
  event: PassEvent;
}

export interface IssuedPassResponse {
  ok: boolean;
  pass: IssuedPass;
}

export interface HistoryEntry {
  convocation: {
    id: number;
    name: string;
    year: string;
    status: string;
    is_active: boolean;
    bucket: "active" | "past";
  };
  registration: PassRegistration & { claimed_at: string };
  event: PassEvent | null;
  honours: {
    department: string;
    student_name: string;
    award_category: string;
    position: string;
    has_photo: boolean;
  }[];
}

export interface HistoryResponse {
  ok: boolean;
  total: number;
  history: HistoryEntry[];
}

function auth(token: string): Record<string, string> {
  return { Authorization: `Bearer ${token}` };
}

export function getPass(token: string): Promise<PassResponse> {
  return request<PassResponse>(PASS, { headers: auth(token) });
}

/** Mint (or reissue) the convocation entry QR. Reissue revokes the prior one. */
export function issuePass(token: string): Promise<IssuedPassResponse> {
  return request<IssuedPassResponse>(`${PASS}/issue`, {
    method: "POST",
    headers: auth(token),
  });
}

export function getHistory(token: string): Promise<HistoryResponse> {
  return request<HistoryResponse>(HISTORY, { headers: auth(token) });
}
