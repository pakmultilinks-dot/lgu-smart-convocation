// Student session token (Phase 5). The bearer token is a credential:
// SecureStore on native, a memory fallback on web (SecureStore has no web
// support) — AsyncStorage is NEVER used for tokens.
import * as SecureStore from "expo-secure-store";
import { Platform } from "react-native";

const KEY_TOKEN = "lgu.student_token";
const memory = new Map<string, string>();

export async function getToken(): Promise<string | null> {
  if (Platform.OS === "web") return memory.get(KEY_TOKEN) ?? null;
  return SecureStore.getItemAsync(KEY_TOKEN);
}

export async function setToken(token: string): Promise<void> {
  if (Platform.OS === "web") {
    memory.set(KEY_TOKEN, token);
    return;
  }
  await SecureStore.setItemAsync(KEY_TOKEN, token, {
    keychainAccessible: SecureStore.WHEN_UNLOCKED,
  });
}

export async function clearToken(): Promise<void> {
  if (Platform.OS === "web") {
    memory.delete(KEY_TOKEN);
    return;
  }
  await SecureStore.deleteItemAsync(KEY_TOKEN);
}
