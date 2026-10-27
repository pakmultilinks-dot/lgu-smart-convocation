import AsyncStorage from "@react-native-async-storage/async-storage";
import Constants from "expo-constants";
import { clearAdminPin } from "./adminAccess";
import { clearScannerSession } from "./scannerSession";
import { clearToken } from "./studentSession";
import { queueCount } from "./offlineQueue";

const KEY_API_BASE_URL = "lgu.api_base_url";
// "custom" is written only when an admin explicitly saves a backend URL.
// Absent (or any other value) means AUTO: discovery decides the backend.
const KEY_API_BASE_URL_MODE = "lgu.api_base_url_mode";
const KEY_VOLUNTEER_NAME = "lgu.volunteer_name";

/** Flask serves on this port on the same laptop that runs Metro. */
const BACKEND_PORT = 5000;

export type ApiBaseMode = "auto" | "custom";

// Backend URL adopted by the discovery fallback for the current JS session.
// Never persisted automatically as "custom" — it only makes the session
// survive a stale stored URL until the next app reload re-discovers.
let sessionBaseUrl: string | null = null;

/**
 * Development backend discovery.
 *
 * Expo Go reports the Metro host for this session (e.g. "192.168.100.5:8081").
 * Flask runs on the same laptop, so http://<host>:5000 tracks the current
 * DHCP lease automatically — a Wi-Fi address change never requires editing
 * source or re-entering the IP on the phone.
 *
 * Production safety: standalone builds expose no Metro host and this returns
 * null; those builds must use an explicitly configured custom backend.
 */
export function getDiscoveredBackendUrl(): string | null {
  try {
    if (Constants.executionEnvironment === "standalone") return null;
    if (!__DEV__) return null;
    const runtimeConfig = Constants.expoConfig as
      | (NonNullable<typeof Constants.expoConfig> & { hostUri?: string })
      | null
      | undefined;
    const hostUri =
      runtimeConfig?.hostUri ??
      (Constants as { manifest?: { hostUri?: string } }).manifest?.hostUri ??
      null;
    if (!hostUri) return null;
    const host = hostUri.split("/")[0]?.split(":")[0]?.trim() ?? "";
    // Hosts are IPv4/IPv6/hostname segments only — never accept a full URL.
    if (!/^[A-Za-z0-9.\-]+$/.test(host)) return null;
    return `http://${host}:${BACKEND_PORT}`;
  } catch {
    return null;
  }
}

function normaliseBaseUrl(raw: string | null): string {
  return (raw ?? "").trim().replace(/\/+$/, "");
}

/** Public deployment address supplied by the build; never contains secrets. */
function getConfiguredBackendUrl(): string {
  const value: unknown = Constants.expoConfig?.extra?.apiBaseUrl;
  if (typeof value !== "string") return "";
  const url = normaliseBaseUrl(value);
  return /^https:\/\/[^\s/?#@]+$/.test(url) ? url : "";
}

export async function getApiBaseUrlMode(): Promise<ApiBaseMode> {
  try {
    const mode = await AsyncStorage.getItem(KEY_API_BASE_URL_MODE);
    return mode === "custom" ? "custom" : "auto";
  } catch {
    return "auto";
  }
}

/**
 * Effective backend URL for the next request.
 *
 * - Custom (explicitly saved by an admin): always honored, never replaced.
 * - Auto: the live development-discovered host wins (DHCP-proof). The last
 *   stored URL is only a fallback when discovery is unavailable (e.g. a
 *   production build with no configuration). A build-configured HTTPS server
 *   is used for a fresh installation. When none exists the result
 *   is "" and callers raise a sanitized "not configured" error.
 */
export async function getApiBaseUrl(): Promise<string> {
  try {
    const [storedRaw, mode] = await Promise.all([
      AsyncStorage.getItem(KEY_API_BASE_URL),
      AsyncStorage.getItem(KEY_API_BASE_URL_MODE),
    ]);
    const stored = normaliseBaseUrl(storedRaw);
    if (mode === "custom" && stored.length > 0) return stored;
    const discovered = getDiscoveredBackendUrl();
    if (discovered) return sessionBaseUrl ?? discovered;
    return sessionBaseUrl ?? (stored || getConfiguredBackendUrl());
  } catch {
    return sessionBaseUrl ?? getDiscoveredBackendUrl() ?? getConfiguredBackendUrl();
  }
}

/** Save an explicitly checked server. Never carry bearer credentials across
 * backends: a host switch could otherwise disclose tokens/PINs to another
 * server. Preserve queued offline admissions instead of redirecting them. */
export async function setApiBaseUrl(url: string): Promise<void> {
  const value = normaliseBaseUrl(url);
  if (!value) throw new Error("Enter a valid server address.");
  const previous = await getApiBaseUrl();
  if (previous !== value) {
    const pending = await queueCount();
    if (pending > 0) {
      throw new Error(
        "Sync your pending offline scans before switching servers.",
      );
    }
    await clearAdminPin();
    await clearScannerSession();
    await clearToken();
  }
  // Fail visibly on storage errors. Never claim "saved" when the next
  // cold start would silently return to an old backend.
  await AsyncStorage.multiSet([
    [KEY_API_BASE_URL, value],
    [KEY_API_BASE_URL_MODE, "custom"],
  ]);
  sessionBaseUrl = value;
}

/**
 * Admin reset: return to automatic discovery. Clears only the mode flag —
 * any last-known-good URL stays behind as a non-persistent fallback.
 * (Named without the use* prefix: eslint react-hooks/rules-of-hooks treats
 * use* calls outside components as hook violations.)
 */
export async function resetToAutomaticBackend(): Promise<void> {
  const previous = await getApiBaseUrl();
  const discovered = getDiscoveredBackendUrl();
  if (previous && previous !== (discovered ?? "")) {
    if ((await queueCount()) > 0) {
      throw new Error("Sync your pending offline scans before switching servers.");
    }
    await clearAdminPin();
    await clearScannerSession();
    await clearToken();
  }
  // Standalone APKs cannot discover Metro: reset must clear the stale URL.
  if (discovered) {
    await AsyncStorage.removeItem(KEY_API_BASE_URL_MODE);
  } else {
    await AsyncStorage.multiRemove([KEY_API_BASE_URL_MODE, KEY_API_BASE_URL]);
  }
  sessionBaseUrl = null;
}
/**
 * 33-QA (I16): a direct health probe against a base URL — shared by the
 * Settings connection pill (the Admin screen keeps its own stricter
 * body-checking probe for the address field).
 */
export async function probeBackend(url: string): Promise<boolean> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 20000);
  try {
    const response = await fetch(`${url}/api/health`, {
      signal: controller.signal,
    });
    if (!response.ok) return false;
    const body: unknown = await response.json();
    if (!body || typeof body !== "object") return false;
    const result = body as { ok?: unknown; app?: unknown };
    return result.ok === true && result.app === "LGU Smart Convocation";
  } catch {
    return false;
  } finally {
    clearTimeout(timer);
  }
}

/**
 * Called when a request against `currentUrl` failed at the network level.
 *
 * 1. A custom URL is the admin's explicit choice — never replaced.
 * 2. In auto mode the live development host is probed (short timeout).
 * 3. If it answers, it becomes the session URL.
 * 4. The working URL is persisted as last-known-good for later fallbacks.
 *
 * Returns the URL to retry against, or null when the original stands.
 */
export async function noteUnreachableBaseUrl(
  currentUrl: string,
): Promise<string | null> {
  try {
    const mode = await getApiBaseUrlMode();
    if (mode === "custom") return null;
    const discovered = getDiscoveredBackendUrl();
    if (!discovered || discovered === currentUrl) return null;
    if (!(await probeBackend(discovered))) return null;
    sessionBaseUrl = discovered;
    await AsyncStorage.setItem(KEY_API_BASE_URL, discovered);
    return discovered;
  } catch {
    return null;
  }
}

export async function getVolunteerName(): Promise<string> {
  return (await AsyncStorage.getItem(KEY_VOLUNTEER_NAME)) ?? "";
}

export async function setVolunteerName(name: string): Promise<void> {
  await AsyncStorage.setItem(KEY_VOLUNTEER_NAME, name.trim());
}

// Recent searches (35I AA): device-local query history for the Search
// screen — the same AsyncStorage pattern as every other local preference;
// no backend call, no analytics, best-effort only.
const KEY_RECENT_SEARCHES = "lgu.recent_searches";
const RECENT_SEARCHES_MAX = 5;

export async function getRecentSearches(): Promise<string[]> {
  try {
    const raw = await AsyncStorage.getItem(KEY_RECENT_SEARCHES);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter((q): q is string => typeof q === "string" && q.trim().length > 0)
      .slice(0, RECENT_SEARCHES_MAX);
  } catch {
    return [];
  }
}

/**
 * Records a query the operator actually typed: trimmed, deduped
 * (case-insensitive), newest first, capped at 5. Never throws — a search
 * must not fail because its history could not be saved.
 */
export async function addRecentSearch(query: string): Promise<void> {
  const q = query.trim();
  if (q.length < 2) return;
  try {
    const existing = await getRecentSearches();
    const next = [
      q,
      ...existing.filter((e) => e.trim().toLowerCase() !== q.toLowerCase()),
    ].slice(0, RECENT_SEARCHES_MAX);
    await AsyncStorage.setItem(KEY_RECENT_SEARCHES, JSON.stringify(next));
  } catch {
    // Ignore — recents are a convenience only.
  }
}

export function isValidBaseUrl(url: string): boolean {
  return /^https?:\/\/[^/\s]+(:\d+)?$/i.test(url.trim());
}
