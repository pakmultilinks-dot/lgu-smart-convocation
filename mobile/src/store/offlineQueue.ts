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

export async function enqueueScan(item: QueuedScan): Promise<QueuedScan[]> {
  const queue = await getQueue();
  queue.push(item);
  await AsyncStorage.setItem(KEY_QUEUE, JSON.stringify(queue));
  return queue;
}

export async function queueCount(): Promise<number> {
  return (await getQueue()).length;
}

/** Remove every queued item whose payload was accepted by the server. */
export async function removeSynced(payloads: string[]): Promise<QueuedScan[]> {
  const remaining = (await getQueue()).filter(
    (item) => !payloads.includes(item.payload),
  );
  await AsyncStorage.setItem(KEY_QUEUE, JSON.stringify(remaining));
  return remaining;
}

export async function clearQueue(): Promise<void> {
  await AsyncStorage.removeItem(KEY_QUEUE);
}
