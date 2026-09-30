import AsyncStorage from "@react-native-async-storage/async-storage";

const KEY_QUEUE = "lgu.offline_scan_queue";

export interface QueuedScan {
  payload: string;
  gate_id: number;
  mode: "entry" | "exit";
  volunteer: string;
  scanned_at: string;
}

function safeParse(raw: string | null): QueuedScan[] {
  if (!raw) {
    return [];
  }
  try {
    const parsed: unknown = JSON.parse(raw);
    return Array.isArray(parsed) ? (parsed as QueuedScan[]) : [];
  } catch {
    return [];
  }
}

export async function getQueue(): Promise<QueuedScan[]> {
  return safeParse(await AsyncStorage.getItem(KEY_QUEUE));
}

export interface EnqueueResult {
  queue: QueuedScan[];
  duplicate: boolean;
}

/**
 * Queue a scan for later upload. The same person scanned twice for the same
 * mode while offline is a double-scan, not two scans: the second one is
 * skipped and reported as a duplicate so the queue (and the sync report)
 * stays honest.
 */
export async function enqueueScan(item: QueuedScan): Promise<EnqueueResult> {
  const queue = await getQueue();
  const duplicate = queue.some(
    (q) => q.payload === item.payload && q.mode === item.mode,
  );
  if (!duplicate) {
    queue.push(item);
    await AsyncStorage.setItem(KEY_QUEUE, JSON.stringify(queue));
  }
  return { queue, duplicate };
}

export async function queueCount(): Promise<number> {
  return (await getQueue()).length;
}

/** Minimal shape of a per-item sync result (mirrors ScanResult in api/client). */
export interface SyncItemResult {
  status: "ok" | "error";
  title: string;
  detail?: string;
}

/**
 * Scan rejections that will never succeed on retry: duplicates, invalid
 * codes, unknown people, and client-side mistakes. These are safe to drop
 * after reporting them; everything else stays queued for the next sync.
 */
const PERMANENT_REJECTIONS = new Set([
  "ALREADY INSIDE",
  "ALREADY USED",
  "NOT INSIDE",
  "INVALID CODE",
  "UNKNOWN CODE",
  "NO GATE SELECTED",
  "NO MODE SELECTED",
  "UNKNOWN GATE",
  "GUEST PASS IS ENTRY ONLY",
]);

export interface SyncReconciliation {
  remaining: QueuedScan[];
  accepted: number;
  rejected: { title: string; detail?: string }[];
}

/**
 * Reconcile the queue against the server's per-item sync results, which the
 * backend returns in the same order as the uploaded items. Drops accepted
 * scans and permanently rejected ones, keeps transient failures queued for
 * retry, and reports every rejected scan so the volunteer knows exactly
 * what did not count. Matching is by position, never by payload, because
 * one person can legitimately have several queued scans (entry then exit).
 */
export async function reconcileSync(
  results: { payload: string; result: SyncItemResult }[],
): Promise<SyncReconciliation> {
  const queue = await getQueue();
  const rejected: { title: string; detail?: string }[] = [];
  let accepted = 0;
  const remaining = queue.filter((_item, index) => {
    const r = results[index]?.result;
    if (!r) {
      return true; // no server verdict for this item: keep it queued
    }
    if (r.status === "ok") {
      accepted += 1;
      return false;
    }
    if (PERMANENT_REJECTIONS.has(r.title)) {
      rejected.push({ title: r.title, detail: r.detail });
      return false;
    }
    return true; // transient failure: retry on the next sync
  });
  await AsyncStorage.setItem(KEY_QUEUE, JSON.stringify(remaining));
  return { remaining, rejected, accepted };
}

export async function clearQueue(): Promise<void> {
  await AsyncStorage.removeItem(KEY_QUEUE);
}
