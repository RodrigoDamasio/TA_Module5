import { expect, test } from "@playwright/test";
import { expectAccessible, finalAnswer, PROD, sendTask } from "./helpers";

test.skip(PROD, "local fake-backend flows (production uses production.spec.ts)");

// E1 + E7 (running and completed)
test("a task runs live: the board shows each agent, then the cited answer", async ({ page }) => {
  await page.goto("/");
  await expectAccessible(page);
  await sendTask(page, "Compare SQLite and PostgreSQL for a small web app.");
  // The SSE loop polls every 0.5 s and the fake agents answer in 0.3 s, so a short "working"
  // state can arrive together with its result: assert the feed, which keeps every step.
  const feed = page.getByRole("region", { name: "Activity feed" });
  await expect(page.getByRole("listitem", { name: /: working$/ }).first()).toBeVisible();
  await expectAccessible(page);
  for (const agent of ["Researcher", "Writer", "Reviewer"]) {
    await expect(feed.getByText(new RegExp(`^${agent} started: `))).toBeVisible();
    await expect(feed.getByText(new RegExp(`^${agent} finished: `))).toBeVisible();
  }
  const answer = finalAnswer(page);
  await expect(answer).toBeVisible();
  await expect(answer.getByRole("link", { name: /^Source 1: / }).first()).toBeVisible();
  await expect(answer.getByRole("region", { name: "Sources" })).toContainText("en.wikipedia.org");
  const transcript = page.getByRole("list", { name: "Transcript" });
  await expect(transcript.getByText(/^Supervisor · decision \d of 5$/)).toHaveCount(4);
  await expect(transcript.getByText(/^Result from /)).toHaveCount(3);
  await expect(page.getByText(/^demo mode \(no LLM\) · model demo · prompt v2 · 7 AI calls/)).toBeVisible();
  await expectAccessible(page);
});

// E2 + E7 (awaiting approval)
test("approval: reject with feedback → revision → approve", async ({ page }) => {
  await page.goto("/");
  await page.getByText(/^Settings:/).click();
  await page.getByLabel("Require my approval before the final answer").check();
  await sendTask(page, "When should I use RAG instead of fine-tuning?");
  await expect(page.getByRole("heading", { name: "Your approval is needed" })).toBeVisible();
  await expectAccessible(page);
  await page.getByLabel("Feedback for a revision (optional)").fill("Add one practical example.");
  await page.getByRole("button", { name: "Reject" }).click();
  const feed = page.getByRole("region", { name: "Activity feed" });
  await expect(feed).toContainText("Your feedback: Add one practical example.");
  await expect(page.getByText("No revisions left: rejecting cancels the run.")).toBeVisible();
  await page.getByRole("button", { name: "Approve" }).click();
  await expect(finalAnswer(page)).toBeVisible();
});

// E3
test("reload: the thread and the run come back from ?run= and storage", async ({ page }) => {
  await page.goto("/");
  await sendTask(page, "Explain HTTP caching for web developers.");
  await expect(finalAnswer(page)).toBeVisible();
  const url = page.url();
  expect(url).toMatch(/\?run=run_[a-f0-9]+$/);
  await page.reload();
  await expect(finalAnswer(page)).toBeVisible();
  await expect(page.getByText(/^You: Explain HTTP caching for web developers\./)).toBeVisible();
  await expect(page.getByRole("list", { name: "Transcript" }).getByText(/^Supervisor · decision/)).toHaveCount(4);
  const fresh = await page.context().newPage();
  await fresh.goto(url); // same browser storage
  await expect(finalAnswer(fresh)).toBeVisible();
});

// E5
test("errors: backend unreachable and rate limited", async ({ page }) => {
  await page.goto("/");
  await page.route("**/run", (route) => route.abort());
  await sendTask(page, "Summarize the history of Python.");
  await expect(page.getByRole("main").getByRole("alert")).toContainText("Can't reach the research service");
  await page.unroute("**/run");
  await page.route("**/run", (route) =>
    route.fulfill({
      status: 429,
      headers: { "Content-Type": "application/problem+json", "Retry-After": "30", "Access-Control-Allow-Origin": "*", "Access-Control-Expose-Headers": "Retry-After" },
      body: JSON.stringify({ type: "http://localhost:8000/problems/rate-limited", title: "Too many requests.", status: 429 }),
    }),
  );
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByRole("main").getByRole("alert")).toContainText("You started too many runs");
  await expect(page.getByText(/You can send again in \d+ s/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Send" })).toBeDisabled();
});
