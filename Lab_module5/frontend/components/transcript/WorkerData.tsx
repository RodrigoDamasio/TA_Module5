import Badge, { type Tone } from "@/components/Badge";
import { FactCheckDataSchema, ReviewDataSchema } from "@/lib/schemas";

const SEVERITY: Record<string, Tone> = { high: "bad", medium: "warn", low: "neutral" };
const CLAIM: Record<string, Tone> = { supported: "good", unsupported: "warn", contradicted: "bad" };

/** The Reviewer's structured output: verdict, issues with severity text, balance flags. */
export function ReviewView({ data }: { data: unknown }) {
  const parsed = ReviewDataSchema.safeParse(data);
  if (!parsed.success) return null;
  const r = parsed.data;
  return (
    <div className="space-y-2 text-sm">
      <p>
        Verdict:{" "}
        <Badge tone={r.verdict === "approve" ? "good" : "warn"}>{r.verdict === "approve" ? "approve" : "revise"}</Badge>
      </p>
      {r.issues.length > 0 ? (
        <ul className="space-y-1">
          {r.issues.map((i, k) => (
            <li key={k} className="flex gap-2">
              <Badge tone={SEVERITY[i.severity] ?? "neutral"}>{i.severity}</Badge>
              <span>{i.text}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p>No issues.</p>
      )}
      <p>
        Balance and wording:{" "}
        {r.balance_flags.length ? r.balance_flags.join("; ") : "no problems found"}
      </p>
    </div>
  );
}

/** The Fact-Checker's claims, each with its status as text. */
export function FactCheckTable({ data }: { data: unknown }) {
  const parsed = FactCheckDataSchema.safeParse(data);
  if (!parsed.success) return null;
  return (
    <div role="region" aria-label="Fact check" tabIndex={0} className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <caption className="sr-only">Claims checked against their sources</caption>
        <thead>
          <tr className="border-b border-zinc-200 dark:border-zinc-800">
            <th scope="col" className="py-1 pr-2 font-medium">Status</th>
            <th scope="col" className="py-1 pr-2 font-medium">Source</th>
            <th scope="col" className="py-1 font-medium">Claim</th>
          </tr>
        </thead>
        <tbody>
          {parsed.data.claims.map((c, k) => (
            <tr key={k} className="border-b border-zinc-100 align-top dark:border-zinc-900">
              <td className="py-1 pr-2">
                <Badge tone={CLAIM[c.status] ?? "neutral"}>{c.status}</Badge>
              </td>
              <td className="py-1 pr-2 font-mono text-xs">{c.source_n ? `[${c.source_n}]` : "—"}</td>
              <td className="py-1">
                {c.sentence}
                {c.note ? <span className="block text-xs text-zinc-600 dark:text-zinc-400">{c.note}</span> : null}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
