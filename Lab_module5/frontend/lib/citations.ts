/** Turns [n] citations into Markdown links to the run's source list, outside code only.
 * Unknown numbers stay plain text; "[1, 2]" is split into "[1][2]" first. */

const GROUPED = /\[(\d{1,3}(?:\s*,\s*\d{1,3})+)\]/g;
const SINGLE = /\[(\d{1,3})\](?!\()/g; // not "[1](url)", which is already a link
const FENCE = /^\s*(```|~~~)/;

export function linkCitations(
  markdown: string,
  known: ReadonlySet<number>,
  anchor: (n: number) => string,
): string {
  let inFence = false;
  return markdown
    .split("\n")
    .map((line) => {
      if (FENCE.test(line)) {
        inFence = !inFence;
        return line;
      }
      if (inFence) return line;
      return line
        .split(/(`[^`]*`)/)
        .map((part, i) => {
          if (i % 2 === 1) return part; // inline code
          return part
            .replace(GROUPED, (_, list: string) =>
              list
                .split(",")
                .map((n) => `[${n.trim()}]`)
                .join(""),
            )
            .replace(SINGLE, (match, n: string) =>
              known.has(Number(n)) ? `[\\[${n}\\]](${anchor(Number(n))})` : match,
            );
        })
        .join("");
    })
    .join("\n");
}

/** Only http(s) links and in-page anchors survive; anything else becomes "" (no link). */
export function safeUrl(url: string): string {
  if (url.startsWith("#")) return url;
  try {
    const parsed = new URL(url);
    return parsed.protocol === "http:" || parsed.protocol === "https:" ? url : "";
  } catch {
    return "";
  }
}
