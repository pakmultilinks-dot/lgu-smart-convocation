import AsyncStorage from "@react-native-async-storage/async-storage";

const KEY_API_BASE_URL = "lgu.api_base_url";
const KEY_VOLUNTEER_NAME = "lgu.volunteer_name";

export const DEFAULT_API_BASE_URL = "http://10.0.2.2:5000";

function normaliseBaseUrl(raw: string | null): string {
  const trimmed = (raw ?? "").trim().replace(/\/+$/, "");
  return trimmed.length > 0 ? trimmed : DEFAULT_API_BASE_URL;
}

export async function getApiBaseUrl(): Promise<string> {
  const stored = await AsyncStorage.getItem(KEY_API_BASE_URL);
  return normaliseBaseUrl(stored);
}

export async function setApiBaseUrl(url: string): Promise<void> {
  await AsyncStorage.setItem(KEY_API_BASE_URL, normaliseBaseUrl(url));
}

export async function getVolunteerName(): Promise<string> {
  return (await AsyncStorage.getItem(KEY_VOLUNTEER_NAME)) ?? "";
}

export async function setVolunteerName(name: string): Promise<void> {
  await AsyncStorage.setItem(KEY_VOLUNTEER_NAME, name.trim());
}

export function isValidBaseUrl(url: string): boolean {
  return /^https?:\/\/[^/\s]+(:\d+)?$/i.test(url.trim());
}
