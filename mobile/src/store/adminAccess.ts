// Administrator PIN store (Phase 35G). The PIN is verified against the
// backend (/api/admin/verify) and kept ONLY on this device; admin POSTs
// (broadcast) attach it as the X-Admin-Pin header. Absent key = locked:
// Broadcast/Admin stay hidden behind the gate until access is granted.
// Phase 38 (MOB-001): the PIN is a credential — stored through the
// secureStorage keystore wrapper (SecureStore on native, in-memory on web),
// with automatic migration of any legacy AsyncStorage row.
import { eraseSecret, readSecret, writeSecret } from "./secureStorage";

const KEY_ADMIN_PIN = "lgu.admin_pin";

// QA fix cycle 4 (Finding 1): one shared wrong-PIN message so the admin
// gate and the live-board exit gate read identically.
export const WRONG_PIN = "Wrong PIN. Try again.";

export async function getAdminPin(): Promise<string | null> {
  try {
    const pin = await readSecret(KEY_ADMIN_PIN);
    return pin && pin.trim().length > 0 ? pin : null;
  } catch {
    return null;
  }
}

export async function setAdminPin(pin: string): Promise<void> {
  try {
    await writeSecret(KEY_ADMIN_PIN, pin);
  } catch {
    // Storage failure keeps the gate locked — the safe default.
  }
}

/** Forget a PIN whenever this device switches to a different backend. */
export async function clearAdminPin(): Promise<void> {
  await eraseSecret(KEY_ADMIN_PIN);
}
