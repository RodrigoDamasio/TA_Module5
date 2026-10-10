/** Display formatting for durations, costs, domains and text. */

export function formatMs(ms: number): string {
  if (ms >= 60_000) return `${Math.floor(ms / 60_000)} min ${Math.round((ms % 60_000) / 1000)} s`;
  if (ms >= 1000) return `${(ms / 1000).toFixed(1)} s`;
  return `${Math.round(ms)} ms`;
}

/** Seconds → "45 s", "2 min 5 s", "about 5 h". */
export function formatDuration(seconds: number): string {
  if (seconds >= 3600) return `about ${Math.round(seconds / 3600)} h`;
  if (seconds >= 60) return `${Math.floor(seconds / 60)} min ${seconds % 60} s`;
  return `${seconds} s`;
}

/** 0.002825 → "$0.0028"; 0 → "$0". */
export function formatCost(usd: number): string {
  if (usd === 0) return "$0";
  if (usd < 0.0001) return "< $0.0001";
  return `$${usd.toFixed(4)}`;
}

/** "https://en.wikipedia.org/wiki/X" → "en.wikipedia.org"; invalid → "". */
export function domain(url: string): string {
  try {
    return new URL(url).hostname;
  } catch {
    return "";
  }
}

export function shorten(text: string, max: number): string {
  const flat = text.replace(/\s+/g, " ").trim();
  return flat.length > max ? `${flat.slice(0, max - 1).trimEnd()}…` : flat;
}

export function plural(n: number, word: string): string {
  return `${n} ${word}${n === 1 ? "" : "s"}`;
}

const FLAG_LABELS: Record<string, string> = {
  forced: "forced completion",
  degraded: "assembled automatically",
  unsourced: "unsourced research",
  possible_injection: "possible prompt injection",
  redacted: "sensitive data redacted",
  unknown_citation: "invalid citations removed",
  truncated: "an answer was cut off",
  canary_leak: "instructions leak blocked",
};

export function flagLabel(flag: string): string {
  return FLAG_LABELS[flag] ?? flag.replaceAll("_", " ");
}
