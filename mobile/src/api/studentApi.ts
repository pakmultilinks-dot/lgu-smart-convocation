// Typed student API (Phase 5): signup verification, sessions, profile
// completion and password recovery. All auth rides the shared request
// helper (status + server code surfaced through ApiError); the bearer
// token lives in studentSession (SecureStore), never AsyncStorage.

import type { Href } from "expo-router";
import { ApiError, request } from "./client";
import { getApiBaseUrl } from "../store/settings";
import { clearToken, setToken } from "../store/studentSession";

const BASE = "/api/student";

export interface Completion {
  verified: boolean;
  claimed: boolean;
  photo: boolean;
  done: number;
  total: number;
  percent: number;
  complete: boolean;
}

export interface StudentProfile {
  phone: string | null;
  photo: boolean;
  photo_updated_at: string | null;
}

export interface StudentRegistration {
  registration_number: string;
  student_name: string;
  roll_number: string;
  department: string;
  status: string;
}

export interface SessionBody {
  ok: boolean;
  account: { id: number; email: string };
  profile: StudentProfile;
  registration: StudentRegistration | null;
  claimed_at: string | null;
  completion: Completion;
}

export interface Session extends SessionBody {
  token: string;
}

export interface VerifyResult {
  ok: boolean;
  challenge_id: number;
  masked_email: string;
  account_exists: boolean;
  pending: boolean;
  resend_remaining: number;
  expires_in: number;
}

export interface ResendResult {
  ok: boolean;
  challenge_id: number;
  resend_remaining: number;
  expires_in: number;
}

/** Phase 38 shared analytics: the student-facing attendance counts — the
    privacy-safe subset only (counts, no names/gates/feed/rejections). */
export interface StudentAttendance {
  registered: number;
  verified: number;
  remaining: number | null;
  percentage: number;
  expected: number;
  attendance_set: boolean;
  generated_at: string;
}

/** ~2 MB (server cap) as base64 characters — checked before upload. */
const MAX_B64_CHARS = Math.ceil((2 * 1024 * 1024) / 3) * 4 + 4;

function auth(token: string): Record<string, string> {
  return { Authorization: `Bearer ${token}` };
}

/** Phase 38: live attendance counts for the student portal (session-scoped,
    GET only — supplementary like readiness; callers catch and show honest
    "unavailable" states, never fabricated numbers). */
export async function fetchAttendance(token: string): Promise<StudentAttendance> {
  const out = await request<{ ok: boolean; attendance: StudentAttendance }>(
    `${BASE}/attendance`,
    { headers: auth(token) },
  );
  return out.attendance;
}

/** Where a signed-in student goes: no claim → verify, incomplete →
 * profile, done → home. One rule, shared by gate, login and signup. */
export function homePath(s: SessionBody): Href {
  if (!s.registration) return "/(student)/verify";
  return s.completion.complete ? "/(student)/home" : "/(student)/profile";
}

async function withSession<T extends SessionBody>(
  path: string,
  body: Record<string, unknown>,
): Promise<T> {
  const out = await request<T>(`${BASE}${path}`, {
    method: "POST",
    body: JSON.stringify(body),
  });
  // Complete/login hand back a fresh token; keep the session alive.
  const token = (out as unknown as { token?: string }).token;
  if (token) await setToken(token);
  return out;
}

export function verify(input: {
  registration_number: string;
  university_email: string;
  roll_number: string;
  student_name: string;
}): Promise<VerifyResult> {
  return request<VerifyResult>(`${BASE}/verify`, {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function resend(challengeId: number): Promise<ResendResult> {
  return request<ResendResult>(`${BASE}/resend`, {
    method: "POST",
    body: JSON.stringify({ challenge_id: challengeId }),
  });
}

export function complete(input: {
  challenge_id: number;
  code: string;
  password?: string;
}): Promise<Session> {
  return withSession<Session>("/complete", input as Record<string, unknown>);
}

export function login(input: {
  email: string;
  password: string;
}): Promise<Session> {
  return withSession<Session>("/login", input);
}

export async function logout(token: string): Promise<void> {
  try {
    await request(`${BASE}/logout`, {
      method: "POST",
      headers: auth(token),
      body: JSON.stringify({}),
    });
  } finally {
    // Local sign-out is unconditional — a dead server never traps the
    // student in a stale session.
    await clearToken();
  }
}

export function me(token: string): Promise<SessionBody> {
  return request<SessionBody>(`${BASE}/me`, { headers: auth(token) });
}

/** Binary photo endpoint — RN <Image> accepts auth headers directly. */
/** Absolute URL + bearer headers for <Image>: RN cannot load a relative
 *  URI, so the route is resolved against the discovered backend host. */
export async function photoSource(token: string): Promise<{ uri: string; headers: Record<string, string> }> {
  const base = await getApiBaseUrl();
  return { uri: `${base}${BASE}/profile/photo`, headers: auth(token) };
}

export function updatePhone(
  token: string,
  phone: string,
): Promise<{ ok: boolean; profile: StudentProfile; completion: Completion }> {
  return request(`${BASE}/profile`, {
    method: "POST",
    headers: auth(token),
    body: JSON.stringify({ phone }),
  });
}

export async function uploadPhoto(
  token: string,
  base64Data: string,
): Promise<{ ok: boolean; profile: StudentProfile; completion: Completion }> {
  if (base64Data.length > MAX_B64_CHARS) {
    // Client-side cap mirrors the server's 2 MB limit — no wasted upload.
    throw new ApiError(
      "That photo is too large. Choose a smaller image (under 2 MB).",
      400,
      "photo",
    );
  }
  return request(`${BASE}/profile/photo`, {
    method: "POST",
    headers: auth(token),
    body: JSON.stringify({ data: base64Data }),
  });
}

export function requestRecovery(email: string): Promise<{ ok: boolean; message: string }> {
  return request(`${BASE}/recovery/request`, {
    method: "POST",
    body: JSON.stringify({ email }),
  });
}

export function completeRecovery(input: {
  email: string;
  code: string;
  password: string;
}): Promise<{ ok: boolean }> {
  return request(`${BASE}/recovery/complete`, {
    method: "POST",
    body: JSON.stringify(input),
  });
}
