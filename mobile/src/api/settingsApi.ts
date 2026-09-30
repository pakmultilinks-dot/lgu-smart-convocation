// Convocation settings API (GET / PUT /api/settings).
// Shared contract for the Volunteer Admin screen and the public Live Board.
// Kept in its own module so the Admin screen and Live Board can both use it
// without editing client.ts.

import { getApiBaseUrl } from "../store/settings";
import { ApiError } from "./client";

export interface ConvocationSettings {
  convocation_name: string;
  convocation_year: string;
  convocation_datetime: string;
  venue: string;
}

const REQUEST_TIMEOUT_MS = 20000;

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const baseUrl = await getApiBaseUrl();
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  let response: Response;
  try {
    response = await fetch(`${baseUrl}${path}`, {
      ...init,
      signal: controller.signal,
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    });
  } catch (e) {
    const timedOut = e instanceof Error && e.name === "AbortError";
    throw new ApiError(
      timedOut
        ? `The server at ${baseUrl} took too long to respond.`
        : `Could not reach the server at ${baseUrl}.`,
      0,
    );
  } finally {
    clearTimeout(timer);
  }
  const body = (await response.json().catch(() => null)) as unknown;
  if (!response.ok) {
    const message =
      body !== null &&
      typeof body === "object" &&
      "error" in body &&
      typeof (body as { error: unknown }).error === "string"
        ? (body as { error: string }).error
        : `Server returned status ${response.status}.`;
    throw new ApiError(message, response.status);
  }
  return body as T;
}

export async function getSettings(): Promise<ConvocationSettings> {
  return request<ConvocationSettings>("/api/settings");
}

export async function updateSettings(
  patch: Partial<ConvocationSettings>,
): Promise<ConvocationSettings> {
  return request<ConvocationSettings>("/api/settings", {
    method: "PUT",
    body: JSON.stringify(patch),
  });
}
