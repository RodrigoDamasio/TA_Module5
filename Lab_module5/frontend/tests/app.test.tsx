import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ResearchApp from "@/components/ResearchApp";
import { threadStore } from "@/hooks/useThread";
import * as api from "@/lib/api";
import { ApiError } from "@/lib/api";
import type { EventHandlers } from "@/lib/events";
import { subscribe } from "@/lib/events";
import type { RunEvent, RunView } from "@/lib/schemas";
import { THREAD_KEY } from "@/lib/thread";
import { agentsList, entry, health, injectionRun, partial, ragRun, runView, samplesList } from "./fixtures";

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    health: vi.fn(),
    agents: vi.fn(),
    samples: vi.fn(),
    sample: vi.fn(),
    startRun: vi.fn(),
    getRun: vi.fn(),
    approve: vi.fn(),
    reject: vi.fn(),
  };
});
vi.mock("@/lib/events", () => ({ subscribe: vi.fn() }));

const mocked = vi.mocked(api);
let streams: EventHandlers[] = [];
let runs: Record<string, RunView> = {};
const RUN = ragRun.run_id;

function emit(event: Omit<RunEvent, "id">, n = 0) {
  act(() => streams[streams.length - 1].onEvent({ ...event, id: n } as RunEvent));
}

function accept(id = RUN) {
  mocked.startRun.mockResolvedValue({ run_id: id, status: "queued", status_url: `/runs/${id}`, events_url: "" });
}

async function send(text = "When should I use RAG instead of fine-tuning?") {
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("Research task"), text);
  await user.click(screen.getByRole("button", { name: "Send" }));
  return user;
}

beforeEach(() => {
  window.localStorage.clear();
  threadStore.reset();
  window.history.replaceState(null, "", "/");
  streams = [];
  runs = { [RUN]: partial(0, { status: "queued" }) };
  vi.mocked(subscribe).mockImplementation((_url, handlers) => {
    streams.push(handlers);
    return { close: () => {} };
  });
  mocked.health.mockResolvedValue(health);
  mocked.agents.mockResolvedValue(agentsList);
  mocked.samples.mockResolvedValue(samplesList);
  mocked.getRun.mockImplementation(async (id: string) => {
    if (!runs[id]) throw new ApiError("not_found", "This run is no longer available.");
    return runs[id];
  });
  mocked.startRun.mockReset();
  mocked.approve.mockReset();
  mocked.reject.mockReset();
});

describe("ResearchApp", () => {
  // C1
  it("renders the composer, settings, samples and the empty state", async () => {
    render(<ResearchApp initialRunId={null} />);
    expect(await screen.findByRole("button", { name: "RAG or fine-tuning?" })).toBeVisible();
    expect(screen.getByText("Settings: 5 decisions max · approval off · memory on")).toBeInTheDocument();
    expect(screen.getByText("Ask a research question.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
    expect(screen.getByText(/Write at least 10 characters/)).toBeInTheDocument();
    expect(screen.getByText("The agents appear here when a run starts.")).toBeInTheDocument();
  });

  // C2
  it("sends a task with the settings, follows the run, blocks a second send", async () => {
    accept();
    render(<ResearchApp initialRunId={null} />);
    const user = userEvent.setup();
    await user.click(screen.getByText(/^Settings:/));
    await user.click(screen.getByLabelText("Require my approval before the final answer"));
    await user.click(screen.getByLabelText("Use memory of earlier tasks"));
    fireEvent.change(screen.getByLabelText("Max decisions"), { target: { value: "3" } });
    await send();
    expect(mocked.startRun).toHaveBeenCalledWith("When should I use RAG instead of fine-tuning?", {
      max_iterations: 3,
      require_approval: true,
      use_memory: false,
    });
    expect(window.location.search).toBe(`?run=${RUN}`);
    expect(await screen.findByText(/Waiting in the queue/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
    expect(screen.getByText(/Wait for the current run to finish/)).toBeInTheDocument();
    expect(JSON.parse(window.localStorage.getItem(THREAD_KEY) ?? "[]")[0].run_id).toBe(RUN);
  });

  // C3, C4
  it("live events drive the agent board, the feed, the status line and parallel work", async () => {
    accept();
    render(<ResearchApp initialRunId={null} />);
    await send();
    await waitFor(() => expect(streams).toHaveLength(1));
    emit({ type: "run_started", data: { iteration: 0, iteration_limit: 5 } });
    emit({ type: "agent_started", data: { agent: "supervisor", iteration: 0, task: null } });
    emit({ type: "decision", data: ragRun.transcript[0] });
    emit({ type: "agent_started", data: { agent: "researcher", iteration: 1, task: "Topics: RAG" } });
    expect(screen.getByRole("listitem", { name: "Researcher: working" })).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Researcher working.");
    expect(screen.getByText("Supervisor → Researcher")).toBeInTheDocument();
    expect(screen.getByText(/Researcher is working/)).toBeInTheDocument();
    // the transcript grows from the events, without a request
    expect(within(screen.getByRole("list", { name: "Transcript" })).getByText("DELEGATE: researcher")).toBeInTheDocument();

    const parallel = ragRun.transcript.find((e) => e.decision?.delegations.length === 2)!;
    emit({ type: "decision", data: parallel });
    emit({ type: "agent_started", data: { agent: "reviewer", iteration: 3, task: "Review" } });
    emit({ type: "agent_started", data: { agent: "fact_checker", iteration: 3, task: "Check" } });
    expect(screen.getByText(/Reviewer and Fact-Checker are working/)).toBeInTheDocument();
    expect(screen.getByText("Supervisor → Reviewer + Fact-Checker (in parallel)")).toBeInTheDocument();
    expect(screen.getByText("These workers ran in parallel.")).toBeInTheDocument();
  });

  // C5, C6
  it("shows the finished answer, sources, transcript details and the meta bar", async () => {
    accept();
    render(<ResearchApp initialRunId={null} />);
    await send();
    await waitFor(() => expect(streams).toHaveLength(1));
    runs[RUN] = ragRun;
    emit({ type: "completed", data: { final_output: ragRun.final_output!, forced: false, degraded: false } });
    const answer = await screen.findByRole("article", { name: "Final answer" });
    expect(within(answer).getByText("AI-generated")).toBeInTheDocument();
    expect(within(answer).getAllByRole("link", { name: /^Source 1: Retrieval-augmented generation/ }).length).toBeGreaterThan(0);
    const sources = within(answer).getByRole("region", { name: "Sources" });
    expect(within(sources).getByRole("link", { name: "Retrieval-augmented generation" })).toHaveAttribute("rel", "noopener noreferrer nofollow");
    expect(within(sources).getAllByText("en.wikipedia.org").length).toBe(ragRun.sources.length);
    expect(screen.getByText(/AI \(Gemini\) · model gemini-3.5-flash-lite · prompt v2/)).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(`Answer ready, ${ragRun.sources.length} sources.`);
    const transcript = screen.getByRole("list", { name: "Transcript" });
    expect(within(transcript).getByText("Supervisor · decision 1 of 5")).toBeInTheDocument();
    expect(within(transcript).getByRole("region", { name: "Fact check" })).toBeInTheDocument();
    expect(within(transcript).getByText(/^Verdict:/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled(); // empty box only
    expect(screen.queryByText(/Wait for the current run/)).not.toBeInTheDocument();
  });

  it("copies and downloads the answer", async () => {
    runs = { [RUN]: ragRun };
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    const createObjectURL = vi.fn(() => "blob:x");
    vi.stubGlobal("URL", Object.assign(URL, { createObjectURL, revokeObjectURL: vi.fn() }));
    render(<ResearchApp initialRunId={RUN} />);
    // fireEvent, not userEvent: userEvent.setup() installs its own clipboard stub
    fireEvent.click(await screen.findByRole("button", { name: "Copy answer" }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith(ragRun.final_output));
    expect(await screen.findByText("Copied")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Download .md" }));
    expect(createObjectURL).toHaveBeenCalled();
  });

  // C7
  it("approval: approve, reject with feedback, conflict", async () => {
    const awaiting = runView({
      status: "awaiting_approval",
      final_output: null,
      approval: { required: true, draft: "## Draft answer [1]", expires_at: new Date(Date.now() + 600_000).toISOString(), revisions: 0 },
    });
    runs = { [RUN]: awaiting };
    render(<ResearchApp initialRunId={RUN} />);
    expect(await screen.findByRole("heading", { name: "Your approval is needed" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /^Draft answer/ })).toBeInTheDocument();
    expect(screen.getByText(/The request expires in (9|10) min/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled(); // just the empty box
    const user = userEvent.setup();
    mocked.reject.mockResolvedValue(runView({ status: "queued", final_output: null }));
    await user.type(screen.getByLabelText("Feedback for a revision (optional)"), "Add a table.");
    await user.click(screen.getByRole("button", { name: "Reject" }));
    expect(mocked.reject).toHaveBeenCalledWith(RUN, "Add a table.");
    mocked.approve.mockRejectedValue(new ApiError("conflict", "The run already moved on."));
    await user.click(screen.getByRole("button", { name: "Approve" }));
    expect(await screen.findByText("The run already moved on.")).toBeInTheDocument();
  });

  it("approval with no revisions left explains that rejecting cancels", async () => {
    runs = {
      [RUN]: runView({ status: "awaiting_approval", final_output: null, approval: { required: true, draft: "Draft", expires_at: null, revisions: 1 } }),
    };
    render(<ResearchApp initialRunId={RUN} />);
    expect(await screen.findByText("No revisions left: rejecting cancels the run.")).toBeInTheDocument();
    mocked.approve.mockResolvedValue(ragRun);
    await userEvent.setup().click(screen.getByRole("button", { name: "Approve" }));
    expect(mocked.approve).toHaveBeenCalledWith(RUN);
  });

  // C8
  it("memory links open earlier runs in the thread", async () => {
    const earlier = runView({ run_id: "run_0ea1", task: "What is RAG?" });
    runs = { [RUN]: runView({ memory_used: [{ run_id: "run_0ea1", task: "What is RAG?" }] }), run_0ea1: earlier };
    render(<ResearchApp initialRunId={RUN} />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "What is RAG?" }));
    await waitFor(() => expect(mocked.getRun).toHaveBeenCalledWith("run_0ea1"));
    expect(await screen.findByText("Showing agents and transcript")).toBeInTheDocument();
    expect(screen.getByText(/Used memory from 1 earlier task/)).toBeInTheDocument();
  });

  // C9
  it("replays a sample without starting a run; 'Run it for real' starts one", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    mocked.sample.mockResolvedValue({ ...ragRun, sample: true });
    render(<ResearchApp initialRunId={null} />);
    fireEvent.click(await screen.findByRole("button", { name: "RAG or fine-tuning?" }));
    expect(await screen.findByText("Stored result — replay (0 AI calls)")).toBeInTheDocument();
    await act(() => vi.advanceTimersByTimeAsync(1500));
    expect(screen.getByRole("listitem", { name: "Supervisor: done" })).toBeInTheDocument();
    await act(() => vi.advanceTimersByTimeAsync(30_000));
    expect(await screen.findByRole("article", { name: "Final answer" })).toBeInTheDocument();
    expect(mocked.startRun).not.toHaveBeenCalled();
    accept();
    fireEvent.click(screen.getByRole("button", { name: "Run it for real" }));
    await waitFor(() => expect(mocked.startRun).toHaveBeenCalledWith(ragRun.task, expect.any(Object)));
  });

  // C10
  it("errors: field errors, rate limit countdown, a missing run", async () => {
    mocked.startRun.mockRejectedValue(new ApiError("validation", "The request is not valid.", undefined, ["Task: too short"]));
    const { unmount } = render(<ResearchApp initialRunId={null} />);
    await send();
    expect(await screen.findByText("Task: too short")).toBeInTheDocument();
    mocked.startRun.mockRejectedValue(new ApiError("rate_limited", "You started too many runs in a short time.", 30));
    await userEvent.setup().click(screen.getByRole("button", { name: "Send" }));
    expect(await screen.findByText(/You can send again in (29|30) s/)).toBeInTheDocument();
    unmount();

    render(<ResearchApp initialRunId="run_dead" />);
    expect(await screen.findByText(/This run is no longer available/)).toBeInTheDocument();
    await userEvent.setup().click(screen.getByRole("button", { name: "Remove from the conversation" }));
    expect(screen.getByText("Ask a research question.")).toBeInTheDocument();
  });

  // C11
  it("service banner: reduced, minimal (send disabled), offline", async () => {
    mocked.health.mockResolvedValue({ ...health, service_level: "minimal", retry_after_s: 7200 });
    const { unmount } = render(<ResearchApp initialRunId={null} />);
    expect(await screen.findByText(/Today's free AI quota is used up/)).toBeInTheDocument();
    expect(screen.getByText(/New runs open again in about 2 h/)).toBeInTheDocument();
    expect(screen.getByText(/^Today's AI quota is used up\. 0\/2000$/)).toBeInTheDocument();
    unmount();
    mocked.health.mockResolvedValue({ ...health, service_level: "reduced" });
    const second = render(<ResearchApp initialRunId={null} />);
    expect(await screen.findByText(/Wikipedia is unavailable right now/)).toBeInTheDocument();
    second.unmount();
    mocked.health.mockRejectedValue(new ApiError("network", "x"));
    render(<ResearchApp initialRunId={null} />);
    expect(await screen.findByText(/can't be reached right now/)).toBeInTheDocument();
  });

  // C12
  it("a lost stream falls back to polling until the run ends", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    accept();
    render(<ResearchApp initialRunId={null} />);
    await send();
    await waitFor(() => expect(streams).toHaveLength(1));
    act(() => streams[0].onLost());
    expect(await screen.findByText(/Live updates interrupted/)).toBeInTheDocument();
    runs[RUN] = ragRun;
    await act(() => vi.advanceTimersByTimeAsync(3500));
    expect(await screen.findByRole("article", { name: "Final answer" })).toBeInTheDocument();
  });

  // C13
  it("restores the thread from storage; the last run is followed", async () => {
    const older = runView({ run_id: "run_01d", task: "Older task" });
    runs = { run_01d: older, [RUN]: partial(2) };
    window.localStorage.setItem(
      THREAD_KEY,
      JSON.stringify([
        { run_id: "run_01d", task: "Older task", created_at: "x" },
        { run_id: RUN, task: ragRun.task, created_at: "y" },
      ]),
    );
    render(<ResearchApp initialRunId={null} />);
    expect(await screen.findByText("Older task")).toBeInTheDocument();
    await waitFor(() => expect(streams).toHaveLength(1)); // only the running one is followed
    expect(await screen.findAllByRole("article", { name: "Final answer" })).toHaveLength(1);
    await userEvent.setup().click(screen.getAllByRole("button", { name: "Show agents and transcript" })[0]);
    expect(screen.getByText(/Selected run:/)).toHaveTextContent("Older task");
  });

  it("failed and cancelled runs, and flags", async () => {
    runs = { [RUN]: runView({ status: "failed", error: "No result could be produced.", final_output: null }) };
    const { unmount } = render(<ResearchApp initialRunId={RUN} />);
    expect(await screen.findByText(/The run failed: No result could be produced/)).toBeInTheDocument();
    unmount();
    runs = { [RUN]: runView({ status: "cancelled", final_output: null }) };
    const second = render(<ResearchApp initialRunId={RUN} />);
    expect(await screen.findByText("This run was cancelled.")).toBeInTheDocument();
    second.unmount();
    runs = { [injectionRun.run_id]: injectionRun };
    render(<ResearchApp initialRunId={injectionRun.run_id} />);
    expect(await screen.findByText(/prompt-injection attempts were found/)).toBeInTheDocument();
    expect(screen.getByText("possible prompt injection")).toBeInTheDocument();
  });

  // C14
  it("renders untrusted Markdown inert: no HTML, no images, no javascript: links", async () => {
    const hostile = [
      "## Title",
      "<script>window.hacked = true</script>",
      "<b>raw html</b>",
      "![tracker](https://evil.example/pixel.png)",
      "[click me](javascript:alert(1)) and [safe](https://en.wikipedia.org/wiki/X) [1]",
      "",
      "| a | b |",
      "|---|---|",
      "| 1 | 2 |",
    ].join("\n");
    runs = { [RUN]: runView({ final_output: hostile }) };
    const { container } = render(<ResearchApp initialRunId={RUN} />);
    const answer = await screen.findByRole("article", { name: "Final answer" });
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
    expect(answer.querySelector("b")).toBeNull();
    expect(within(answer).getByText("[image: tracker]")).toBeInTheDocument();
    expect(within(answer).queryByRole("link", { name: /click me/ })).toBeNull();
    expect(within(answer).getByText("click me").tagName).toBe("SPAN");
    expect(within(answer).getByRole("link", { name: /safe/ })).toHaveAttribute("target", "_blank");
    expect(within(answer).getByRole("region", { name: "Table" })).toBeInTheDocument();
    expect((window as { hacked?: boolean }).hacked).toBeUndefined();
  });

  it("notices and feedback appear in the transcript", async () => {
    runs = {
      [RUN]: runView({
        transcript: [
          ...ragRun.transcript,
          entry({ seq: 99, kind: "feedback", agent: "human", text: "Please add costs." }),
          entry({ seq: 100, kind: "notice", text: "Used 1 memories from earlier tasks." }),
        ],
      }),
    };
    render(<ResearchApp initialRunId={RUN} />);
    const transcript = await screen.findByRole("list", { name: "Transcript" });
    expect(within(transcript).getByText("Please add costs.")).toBeInTheDocument();
    expect(within(transcript).getByText("Used 1 memories from earlier tasks.")).toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: "Activity feed" })).getByText("Your feedback: Please add costs.")).toBeInTheDocument();
  });
});
