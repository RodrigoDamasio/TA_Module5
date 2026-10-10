import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import { linkCitations, safeUrl } from "@/lib/citations";
import { domain } from "@/lib/format";
import type { Source } from "@/lib/schemas";

export const sourceAnchor = (runId: string, n: number) => `${runId}-source-${n}`;

/** Model output is untrusted: no raw HTML, no images, only http(s) links (domain shown),
 * and [n] citations linked to the run's source list. */
export default function Markdown({
  text,
  sources = [],
  runId,
}: {
  text: string;
  sources?: Source[];
  runId: string;
}) {
  const byN = new Map(sources.map((s) => [s.n, s]));
  const linked = linkCitations(text, new Set(byN.keys()), (n) => `#${sourceAnchor(runId, n)}`);

  const components: Components = {
    a({ href, children }) {
      if (!href) return <span>{children}</span>;
      if (href.startsWith("#")) {
        const n = Number(href.split("-source-")[1]);
        const s = byN.get(n);
        return (
          <a
            href={href}
            aria-label={s ? `Source ${n}: ${s.title}` : undefined}
            className="mx-0.5 rounded bg-orange-50 px-1 font-mono text-xs font-semibold text-orange-800 no-underline hover:underline dark:bg-orange-950 dark:text-orange-200"
          >
            {children}
          </a>
        );
      }
      return (
        <a href={href} target="_blank" rel="noopener noreferrer nofollow" className="text-orange-800 underline dark:text-orange-300">
          {children}
          <span className="text-xs text-zinc-600 dark:text-zinc-400"> ({domain(href)})</span>
        </a>
      );
    },
    img({ alt }) {
      return <span className="text-zinc-600 italic dark:text-zinc-400">[image{alt ? `: ${alt}` : ""}]</span>;
    },
    table({ children }) {
      return (
        <div role="region" aria-label="Table" tabIndex={0} className="my-3 overflow-x-auto">
          <table className="w-full border-collapse text-sm">{children}</table>
        </div>
      );
    },
    pre({ children }) {
      return (
        <pre tabIndex={0} className="my-3 overflow-x-auto rounded-md bg-zinc-100 p-3 text-sm dark:bg-zinc-900">
          {children}
        </pre>
      );
    },
  };

  return (
    <div className="markdown">
      <ReactMarkdown remarkPlugins={[remarkGfm]} skipHtml urlTransform={safeUrl} components={components}>
        {linked}
      </ReactMarkdown>
    </div>
  );
}
