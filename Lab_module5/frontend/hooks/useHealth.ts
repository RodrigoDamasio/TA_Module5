import { useCallback, useEffect, useState } from "react";
import * as api from "@/lib/api";
import type { Health } from "@/lib/schemas";

export type ServiceLevel = "full" | "reduced" | "minimal" | "offline" | "unknown";

const EVERY_MS = 60_000;

/** /health polled every minute: the service level (graceful degradation, course §1.4). */
export function useHealth() {
  const [health, setHealth] = useState<Health | null>(null);
  const [offline, setOffline] = useState(false);
  const [retryAt, setRetryAt] = useState<number | null>(null); // quota reset (ms timestamp)

  const load = useCallback(() => {
    api.health().then(
      (h) => {
        setHealth(h);
        setOffline(false);
        setRetryAt(h.retry_after_s ? Date.now() + h.retry_after_s * 1000 : null);
      },
      () => setOffline(true),
    );
  }, []);

  useEffect(() => {
    const first = setTimeout(load, 0);
    const timer = setInterval(load, EVERY_MS);
    return () => {
      clearTimeout(first);
      clearInterval(timer);
    };
  }, [load]);

  const level: ServiceLevel = offline ? "offline" : (health?.service_level ?? "unknown");
  return { health, level, retryAt, reload: load };
}
