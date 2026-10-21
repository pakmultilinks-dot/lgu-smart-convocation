// Convocation settings API (GET / PUT /api/settings).
// Administrator-only module: the Admin screen is its sole caller. The public
// Live Board and every other surface read GET /api/config through client.ts
// (fetchAppConfig) — that endpoint stays anonymous for kiosk, landing page
// and connectivity discovery, and carries the same event identity.
//
// Phase 35K (Part T): PUT requires the administrator PIN — the backend
// rejects settings changes without the X-Admin-Pin header. Phase 28: GET
// now requires the same PIN (read/write halves of one resource share one
// policy). The PIN is read from the on-device admin gate and attached here
// so screens don't repeat the header logic.

import { getApiBaseUrl, noteUnreachableBaseUrl } from "../store/settings";
import { getAdminPin } from "../store/adminAccess";
import { ApiError } from "./client";

export interface ConvocationSettings {
  convocation_name: string;
  convocation_year: string;
  convocation_datetime: string;
  venue: string;
  /** Admin-configured expected attendance, stored as a numeric string. */
  expected_attendance: string;
  /** Institution name shown on event screens (saved via Admin, 35K). */
  university_name: string;
}

const REQUEST_TIMEOUT_MS = 20000;

function networkError(timedOut: boolean): ApiError {
  return new ApiError(
    timedOut
      ? "The connection is taking too long. Please check your Wi-Fi connection and try again."
      : "Unable to connect. Please check your Wi-Fi connection or contact the system administrator.",
    0,
  );
}

async function send(url: string, init?: RequestInit): Promise<Response> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    return await fetch(url, {
      ...init,
      signal: controller.signal,
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    });
  } finally {
    clearTimeout(timer);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const baseUrl = await getApiBaseUrl();
  if (baseUrl.length === 0) {
    // Production safety: nothing configured and no development host to
    // discover from. Sanitized message only — no URLs in user UI.
    throw new ApiError(
      "This device is not configured to reach the convocation server. Ask the administrator to set the backend under Admin > Backend Connection.",
      0,
    );
  }
  let response: Response;
  try {
    response = await send(`${baseUrl}${path}`, init);
  } catch (e) {
    const timedOut = e instanceof Error && e.name === "AbortError";
    // Technical diagnostics stay in the developer console only (plain log:
    // Expo Go LogBox floats warn/error banners into the user UI, which must
    // never show raw API errors, base URLs, or IPs). The sanitized
    // ApiError message below is what reaches ErrorState on the device.
    if (__DEV__) {
      console.log(`[api] ${path} request failed:`, { baseUrl, error: e });
    }
    // Stale-URL recovery mirrors client.ts: auto mode probes the discovered
    // development host and retries once; custom URLs are never replaced.
    const fallback = await noteUnreachableBaseUrl(baseUrl);
    if (fallback) {
      if (__DEV__) {
        console.log(`[api] ${path} retrying on discovered backend:`, fallback);
      }
      try {
        response = await send(`${fallback}${path}`, init);
      } catch (e2) {
        const retryTimedOut = e2 instanceof Error && e2.name === "AbortError";
        throw networkError(retryTimedOut);
      }
    } else {
      throw networkError(timedOut);
    }
  }
  const body = (await response.json().catch(() => null)) as unknown;
  if (!response.ok) {
    const message =
      body !== null &&
      typeof body === "object" &&
      "error" in body &&
      typeof (body as { error: unknown }).error === "string"
        ? (body as { error: string }).error
        : "The service is temporarily unavailable. Please try again.";
    throw new ApiError(message, response.status);
  }
  return body as T;
}

export async function getSettings(): Promise<ConvocationSettings> {
  // Phase 28: reading the settings is an administrator action — the backend
  // gates GET with the same X-Admin-Pin as PUT. The Admin screen only mounts
  // after AdminGate has verified this PIN against the server, so it is always
  // available here; without one the request is refused rather than answered.
  const adminPin = await getAdminPin();
  return request<ConvocationSettings>("/api/settings", {
    headers: adminPin ? { "X-Admin-Pin": adminPin } : undefined,
  });
}

export async function updateSettings(
  patch: Partial<ConvocationSettings>,
): Promise<ConvocationSettings> {
  // Phase 35K (Part T): the backend rejects settings changes without the
  // administrator PIN — the on-device gate PIN is attached here.
  const adminPin = await getAdminPin();
  return request<ConvocationSettings>("/api/settings", {
    method: "PUT",
    headers: adminPin ? { "X-Admin-Pin": adminPin } : undefined,
    body: JSON.stringify(patch),
  });
}
