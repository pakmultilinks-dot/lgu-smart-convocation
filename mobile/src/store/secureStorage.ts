// Phase 38 (MOB-001): shared secret storage. Scanner sessions and the
// administrator PIN are credentials — they live in the platform keystore
// (expo-secure-store) on native, never in AsyncStorage. SecureStore has no
// web support, so web keeps an in-memory fallback (same rule as
// studentSession). A value previously persisted in AsyncStorage is migrated
// to the keystore on first read and the legacy row is removed, so existing
// signed-in devices upgrade transparently instead of logging everyone out.
import AsyncStorage from "@react-native-async-storage/async-storage";
import * as SecureStore from "expo-secure-store";
import { Platform } from "react-native";

const KEYCHAIN_OPTS = {
  keychainAccessible: SecureStore.WHEN_UNLOCKED,
};
// Web fallback only — one in-memory map keyed by the store's key.
const memory = new Map<string, string>();

export async function readSecret(key: string): Promise<string | null> {
  if (Platform.OS === "web") return memory.get(key) ?? null;
  try {
    const value = await SecureStore.getItemAsync(key);
    if (value !== null) return value;
    // Legacy migration: the value was stored under the old AsyncStorage
    // key — move it into the keystore and drop the plaintext row.
    const legacy = await AsyncStorage.getItem(key);
    if (legacy === null) return null;
    await SecureStore.setItemAsync(key, legacy, KEYCHAIN_OPTS);
    await AsyncStorage.removeItem(key);
    return legacy;
  } catch {
    return null; // Storage failure = locked/signed out — the safe default.
  }
}

export async function writeSecret(key: string, value: string): Promise<void> {
  if (Platform.OS === "web") {
    memory.set(key, value);
    return;
  }
  await SecureStore.setItemAsync(key, value, KEYCHAIN_OPTS);
}

export async function eraseSecret(key: string): Promise<void> {
  if (Platform.OS === "web") {
    memory.delete(key);
    return;
  }
  try {
    await SecureStore.deleteItemAsync(key);
    await AsyncStorage.removeItem(key); // clear any legacy plaintext copy too
  } catch {
    // Ignore; the credential persists until the next successful clear.
  }
}
