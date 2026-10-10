"use client";
import { useCountdown } from "@/hooks/useCountdown";
import type { ServiceLevel } from "@/hooks/useHealth";
import { formatDuration } from "@/lib/format";

/** Graceful degradation made visible (course §1.4). Nothing is shown at "full". */
export default function ServiceBanner({
  level,
  retryAt,
}: {
  level: ServiceLevel;
  retryAt: number | null; // ms timestamp of the quota reset
}) {
  const left = useCountdown(level === "minimal" ? retryAt : null);
  if (level === "full" || level === "unknown") return null;
  const text = {
    reduced: "Wikipedia is unavailable right now: answers are written without sources.",
    minimal: `Today's free AI quota is used up. The samples still work.${left > 0 ? ` New runs open again in ${formatDuration(left)}.` : ""}`,
    offline: "The research service can't be reached right now. Try again in a minute.",
  }[level];
  return (
    <div role="status" className="rounded-md border border-amber-400 bg-amber-50 p-2 text-sm text-amber-900 dark:border-amber-700 dark:bg-amber-950 dark:text-amber-100">
      <span className="font-medium">Service {level}:</span> {text}
    </div>
  );
}
