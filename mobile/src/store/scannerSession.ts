// Volunteer scanner session (Phase 14). A volunteer signs in once with a
// per-account username + PIN; the server returns a short-lived bearer token
// that the app holds ONLY on this device and attaches to /api/scan and
// /api/sync. No shared/default credential — every device is provisioned by
// the administrator. Absent/expired token = locked: the Scanner shows the
// sign-in prompt and no scan leaves the device.
// Phase 38 (MOB-001): the token is a credential — stored through the
// secureStorage keystore wrapper (SecureStore on native, in-memory on web),
// with automatic migration of any legacy AsyncStorage row. AsyncStorage is
// no longer written for this key.
import { eraseSecret, readSecret, writeSecret } from "./secureStorage";

export interface ScannerSession {
  token: string;
  expiresAt: string;
  username: string;
  displayName: string;
  /** Server-assigned gates this scanner may admit through. */
  gates: number[];
}

const KEY_SESSION = "lgu.scanner_session";

export async function getScannerSession(): Promise<ScannerSession | null> {
  try {
    const raw = await readSecret(KEY_SESSION);
    if (!raw) return null;
    const s = JSON.parse(raw) as ScannerSession;
    // Expired locally → treat as signed out (server would reject it too).
    if (!s?.token || (s.expiresAt && Date.parse(s.expiresAt) <= Date.now())) {
      return null;
    }
    return s;
  } catch {
    return null;
  }
}

export async function setScannerSession(s: ScannerSession): Promise<void> {
  try {
    await writeSecret(KEY_SESSION, JSON.stringify(s));
  } catch {
    // Storage failure leaves the scanner signed out — the safe default.
  }
}

export async function clearScannerSession(): Promise<void> {
  try {
    await eraseSecret(KEY_SESSION);
  } catch {
    // Ignore; the token simply persists until the next successful clear.
  }
}
