import AsyncStorage from "@react-native-async-storage/async-storage";

export type AppMode = "volunteer" | "liveboard";

const KEY_APP_MODE = "lgu.app_mode";

export async function getAppMode(): Promise<AppMode | null> {
  const stored = await AsyncStorage.getItem(KEY_APP_MODE);
  if (stored === "volunteer" || stored === "liveboard") {
    return stored;
  }
  return null;
}

export async function setAppMode(mode: AppMode): Promise<void> {
  await AsyncStorage.setItem(KEY_APP_MODE, mode);
}

export async function clearAppMode(): Promise<void> {
  await AsyncStorage.removeItem(KEY_APP_MODE);
}
