import { useSyncExternalStore } from "react";
import { loadThread, saveThread, type ThreadItem } from "@/lib/thread";

/** The thread as an external store over localStorage: the server renders an empty thread and
 * the browser its saved one, without a hydration mismatch or a setState in an effect. */
let cache: ThreadItem[] | null = null;
const listeners = new Set<() => void>();
const SERVER_SNAPSHOT: ThreadItem[] = [];

export const threadStore = {
  get(): ThreadItem[] {
    if (cache === null) cache = loadThread();
    return cache;
  },
  set(items: ThreadItem[]): void {
    cache = items;
    saveThread(items);
    listeners.forEach((l) => l());
  },
  subscribe(listener: () => void): () => void {
    listeners.add(listener);
    return () => listeners.delete(listener);
  },
  /** Tests: forget the cached snapshot. */
  reset(): void {
    cache = null;
  },
};

export function useThread(): [ThreadItem[], (items: ThreadItem[]) => void] {
  const items = useSyncExternalStore(threadStore.subscribe, threadStore.get, () => SERVER_SNAPSHOT);
  return [items, threadStore.set];
}
