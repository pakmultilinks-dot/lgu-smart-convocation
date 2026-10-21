import AsyncStorage from "@react-native-async-storage/async-storage";

// Volunteer operational state that must survive navigation between tabs:
// which gate is selected, whether the scanner is in Entry or Exit mode, and
// the most recent real scan result. Written by ScannerScreen, read by
// HomeScreen so the home screen can show current operations at a glance.

const KEY_SELECTED_GATE = "lgu.ops_selected_gate";
const KEY_SCAN_MODE = "lgu.ops_scan_mode";
const KEY_SCAN_OCCASION = "lgu.ops_scan_occasion";
const KEY_LAST_RESULT = "lgu.ops_last_result";

export interface SelectedGate {
  id: number;
  label: string;
}

export type ScanMode = "entry" | "exit";
/** Which occasion of the annual cycle the scanner records (Phase 29). */
export type ScanOccasion = "rehearsal" | "ceremony";

export interface OpsScanResult {
  level: "green" | "red" | "amber";
  title: string;
  name?: string | null;
  sub?: string | null;
  detail?: string | null;
  gate?: string | null;
  time?: string | null;
  /** Device timestamp (Date.now) of when the result was recorded. */
  at: number;
}

async function readJson<T>(key: string): Promise<T | null> {
  try {
    const raw = await AsyncStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : null;
  } catch {
    return null;
  }
}

async function writeJson(key: string, value: unknown): Promise<void> {
  try {
    await AsyncStorage.setItem(key, JSON.stringify(value));
  } catch {
    // Persistence is best-effort; the scanner keeps working without it.
  }
}

export async function getSelectedGate(): Promise<SelectedGate | null> {
  return readJson<SelectedGate>(KEY_SELECTED_GATE);
}

export async function setSelectedGate(gate: SelectedGate): Promise<void> {
  await writeJson(KEY_SELECTED_GATE, gate);
}

export async function getScanMode(): Promise<ScanMode> {
  const mode = await AsyncStorage.getItem(KEY_SCAN_MODE);
  return mode === "exit" ? "exit" : "entry";
}

export async function setScanMode(mode: ScanMode): Promise<void> {
  try {
    await AsyncStorage.setItem(KEY_SCAN_MODE, mode);
  } catch {
    // Best-effort.
  }
}

export async function getScanOccasion(): Promise<ScanOccasion> {
  const v = await AsyncStorage.getItem(KEY_SCAN_OCCASION);
  return v === "rehearsal" ? "rehearsal" : "ceremony";
}

export async function setScanOccasion(occasion: ScanOccasion): Promise<void> {
  try {
    await AsyncStorage.setItem(KEY_SCAN_OCCASION, occasion);
  } catch {
    // Best-effort.
  }
}

export async function getLastScanResult(): Promise<OpsScanResult | null> {
  return readJson<OpsScanResult>(KEY_LAST_RESULT);
}

export async function setLastScanResult(result: OpsScanResult): Promise<void> {
  await writeJson(KEY_LAST_RESULT, result);
}
