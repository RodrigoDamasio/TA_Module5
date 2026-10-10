/** The conversation thread kept in the browser: run ids and tasks only (the runs live on the
 * server). Storage can be missing or blocked (private mode): every access is guarded. */
import { z } from "zod";

export const THREAD_KEY = "research-thread-v1";
export const MAX_THREAD = 20;

const ItemSchema = z.object({ run_id: z.string().regex(/^run_[a-f0-9]+$/), task: z.string(), created_at: z.string() });
export type ThreadItem = z.infer<typeof ItemSchema>;

function storage(): Storage | null {
  try {
    return globalThis.localStorage ?? null;
  } catch {
    return null;
  }
}

export function loadThread(): ThreadItem[] {
  try {
    const raw = storage()?.getItem(THREAD_KEY);
    if (!raw) return [];
    const parsed = z.array(ItemSchema).safeParse(JSON.parse(raw));
    return parsed.success ? parsed.data.slice(-MAX_THREAD) : [];
  } catch {
    return [];
  }
}

export function saveThread(items: ThreadItem[]): void {
  try {
    storage()?.setItem(THREAD_KEY, JSON.stringify(items.slice(-MAX_THREAD)));
  } catch {
    // Quota or blocked storage: the thread just isn't remembered.
  }
}

/** Appends (or moves to the end) a run; keeps the newest MAX_THREAD. */
export function addToThread(items: ThreadItem[], item: ThreadItem): ThreadItem[] {
  return [...items.filter((i) => i.run_id !== item.run_id), item].slice(-MAX_THREAD);
}

export function removeFromThread(items: ThreadItem[], runId: string): ThreadItem[] {
  return items.filter((i) => i.run_id !== runId);
}
