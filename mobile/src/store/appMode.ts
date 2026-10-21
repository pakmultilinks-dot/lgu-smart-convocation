import AsyncStorage from "@react-native-async-storage/async-storage";
import type { ScanMode } from "./ops";

export type AppMode = "volunteer" | "liveboard" | "student";

const KEY_APP_MODE = "lgu.app_mode";

const MODES: AppMode[] = ["volunteer", "liveboard", "student"];

export async function getAppMode(): Promise<AppMode | null> {
  const stored = await AsyncStorage.getItem(KEY_APP_MODE);
  return MODES.includes(stored as AppMode) ? (stored as AppMode) : null;
}

export async function setAppMode(mode: AppMode): Promise<void> {
  await AsyncStorage.setItem(KEY_APP_MODE, mode);
}

export async function clearAppMode(): Promise<void> {
  await AsyncStorage.removeItem(KEY_APP_MODE);
}

/**
 * The ONE rule deciding whether picking `next` may change this device
 * (33-QA I21 / Phase 27 E3).
 *
 * Confirmation is required unless the device is PROVABLY already on `next`,
 * so an unknown current mode (`null` — cleared, wiped, erroring or first
 * run) asks as well. That makes the guard fail-closed: no entry point can
 * reach a silent switch simply by arriving with nothing stored. Picking a
 * surface is navigation only — it grants no access and changes no session.
 */
export function needsModeConfirmation(
  current: AppMode | null,
  next: AppMode,
): boolean {
  return current !== next;
}

/**
 * The same fail-closed rule for Entry/Exit on the volunteer Home screen
 * (Phase 28, concern 2), deliberately the same shape as the mode rule above
 * so the two surface switches cannot drift apart. The old Home control
 * committed every tap straight to storage — one tap silently turned the
 * device from admitting guests to releasing them. A change is confirmed
 * unless the control is provably already on the requested direction, so an
 * unknown stored direction (`null` — cleared, wiped, erroring or first run)
 * asks as well. `current === next` is a re-tap, not a change, and is not
 * confirmed. Direction is an operating choice, not a credential: this gate
 * stops an accidental switch, it does not grant access.
 */
export function needsScanModeConfirmation(
  current: ScanMode | null,
  next: ScanMode,
): boolean {
  return current !== next;
}
