"use client";
import { useState } from "react";
import Markdown from "@/components/answer/Markdown";
import { useCountdown } from "@/hooks/useCountdown";
import { formatDuration } from "@/lib/format";
import type { RunView } from "@/lib/schemas";

const MAX_REVISIONS = 1;

/** Human approval (extension, from Lab 3): the draft answer, approve or reject with
 * feedback (one revision), and the time left before the request expires. */
export default function ApprovalPanel({
  run,
  busy,
  feedbackMax,
  onApprove,
  onReject,
}: {
  run: RunView;
  busy: boolean;
  feedbackMax: number;
  onApprove: () => void;
  onReject: (feedback: string | null) => void;
}) {
  const [feedback, setFeedback] = useState("");
  const expires = run.approval.expires_at ? Date.parse(run.approval.expires_at) : null;
  const left = useCountdown(Number.isNaN(expires) ? null : expires);
  const revisionsLeft = Math.max(0, MAX_REVISIONS - run.approval.revisions);

  return (
    <section aria-labelledby={`approval-${run.run_id}`} className="space-y-3 rounded-lg border-2 border-blue-700 bg-blue-50 p-3 dark:bg-blue-950">
      <h3 id={`approval-${run.run_id}`} className="font-semibold">
        Your approval is needed
      </h3>
      <p className="text-sm">
        The Supervisor proposed this answer. Approve it, or reject it
        {revisionsLeft ? " with feedback to get one revision" : ""}.
        {expires !== null && left > 0 && <> The request expires in {formatDuration(left)}.</>}
      </p>
      <div className="rounded-md border border-blue-200 bg-white p-3 dark:border-blue-900 dark:bg-zinc-950">
        <Markdown text={run.approval.draft ?? ""} sources={run.sources} runId={run.run_id} />
      </div>
      <label className="block text-sm">
        <span className="font-medium">Feedback for a revision (optional)</span>
        <textarea
          value={feedback}
          maxLength={feedbackMax}
          rows={2}
          disabled={revisionsLeft === 0}
          onChange={(e) => setFeedback(e.target.value)}
          placeholder={revisionsLeft ? "e.g. Add a short comparison table." : "No revisions left"}
          className="mt-1 block w-full rounded-md border border-zinc-300 bg-white p-2 dark:border-zinc-600 dark:bg-zinc-900"
        />
      </label>
      <p className="text-xs text-zinc-700 dark:text-zinc-300">
        {revisionsLeft
          ? "Reject with feedback: the agents revise once. Reject without feedback: the run is cancelled."
          : "No revisions left: rejecting cancels the run."}
      </p>
      <div className="flex flex-wrap gap-3">
        <button type="button" disabled={busy} onClick={onApprove} className="rounded-md bg-blue-700 px-4 py-1.5 text-sm font-medium text-white hover:bg-blue-800 disabled:bg-zinc-500">
          Approve
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={() => onReject(feedback.trim() || null)}
          className="rounded-md border border-blue-700 px-4 py-1.5 text-sm font-medium text-blue-800 disabled:opacity-50 dark:text-blue-200"
        >
          Reject
        </button>
      </div>
    </section>
  );
}
