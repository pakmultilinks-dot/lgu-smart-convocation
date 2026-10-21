import AsyncStorage from "@react-native-async-storage/async-storage";

const KEY_QUEUE = "lgu.offline_scan_queue";

/** Which occasion a queued scan records (Phase 29). Kept as a literal
    union here (same values as client.ts Occasion) so this store compiles
    standalone — the test harness builds it as a single file, outside the
    RN project's ambient globals. */
export type QueuedOccasion = "rehearsal" | "ceremony";

export interface QueuedScan {
  payload: string;
  gate_id: number;
  mode: "entry" | "exit";
  volunteer: string;
  scanned_at: string;
  /** Which occasion this scan admits (Phase 29); older queued rows without
      it replay server-side as the main convocation. */
  occasion: QueuedOccasion;
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

/** Serializes every read-modify-write on the queue. AsyncStorage has no
 *  transactions, so reconcileSync's "read → filter → overwrite" and
 *  enqueueScan's "read → append → overwrite" must never interleave — a
 *  scan enqueued during reconciliation would otherwise be silently dropped
 *  by the following overwrite. Reads (getQueue) stay lock-free. */
let queueLock: Promise<unknown> = Promise.resolve();

function withQueueLock<T>(fn: () => Promise<T>): Promise<T> {
  const run = queueLock.then(fn, fn);
  queueLock = run.then(() => undefined, () => undefined);
  return run;
}

export interface EnqueueResult {
  queue: QueuedScan[];
  duplicate: boolean;
}

/**
 * Queue a scan for later upload. The same person scanned twice for the same
 * mode AND occasion while offline is a double-scan, not two scans: the
 * second one is skipped and reported as a duplicate so the queue (and the
 * sync report) stays honest. Occasion is part of the key — the same pass
 * checked in for the rehearsal and later for the main convocation are two
 * legitimate queued scans.
 */
export async function enqueueScan(item: QueuedScan): Promise<EnqueueResult> {
  return withQueueLock(async () => {
    const queue = await getQueue();
    const duplicate = queue.some(
      (q) =>
        q.payload === item.payload &&
        q.mode === item.mode &&
        (q.occasion ?? "ceremony") === item.occasion,
    );
    if (!duplicate) {
      queue.push(item);
      await AsyncStorage.setItem(KEY_QUEUE, JSON.stringify(queue));
    }
    return { queue, duplicate };
  });
}

export async function queueCount(): Promise<number> {
  return (await getQueue()).length;
}

/** Minimal shape of a per-item sync result (mirrors ScanResult in api/client).
    "busy" is transient contention: reconcileSync keeps it queued. */
export interface SyncItemResult {
  status: "ok" | "error" | "busy";
  title: string;
  detail?: string;
}

/**
 * Scan rejections that will never succeed on retry: duplicates, invalid
 * codes, unknown people, client-side mistakes, gate-authorization failures,
 * and scans an earlier sync already recorded ("ALREADY SYNCED", Phase 35K
 * Part O — re-sending a queued batch must never double-count entries;
 * "ALREADY ADMITTED", Phase 24D — the convocation ledger's duplicate
 * answer, which a replay of an already-admitted scan also produces and
 * which must therefore be dropped, not retried forever). These are safe to
 * drop after reporting them; everything else stays queued for the next sync.
 * Exported so tests can assert it against the backend's permanent titles.
 */
export const PERMANENT_REJECTIONS = new Set([
  "ALREADY INSIDE",
  "ALREADY USED",
  "ALREADY SYNCED",
  "ALREADY ADMITTED",
  "GATE NOT AUTHORIZED",
  "NOT INSIDE",
  "INVALID CODE",
  "UNKNOWN CODE",
  "NO GATE SELECTED",
  "NO MODE SELECTED",
  "UNKNOWN GATE",
  "GUEST PASS IS ENTRY ONLY",
  // Phase 29: the scan named an occasion this convocation cannot record —
  // no rehearsal is configured (schedule it and publish, then scan again),
  // or the device sent a value the server does not know. Neither ever
  // succeeds on blind retry.
  "REHEARSAL NOT SCHEDULED",
  "UNKNOWN OCCASION",
  // Phase 34 (Part C): the pass was revoked while this scan sat offline —
  // revocation invalidates the bearer credential, so replay never admits.
  "GUEST PASS REVOKED",
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
  return withQueueLock(async () => {
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
  });
}

export async function clearQueue(): Promise<void> {
  await withQueueLock(() => AsyncStorage.removeItem(KEY_QUEUE));
}
