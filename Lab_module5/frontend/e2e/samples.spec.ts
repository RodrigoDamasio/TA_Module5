import { expect, test } from "@playwright/test";
import { expectAccessible, expectNoHorizontalScroll, finalAnswer } from "./helpers";

// E4 (local and production: 0 LLM calls)
test("each sample replays its stored run without starting one", async ({ page }) => {
  const posts: string[] = [];
  page.on("request", (r) => r.method() === "POST" && posts.push(r.url()));
  await page.goto("/");
  const chips = page.getByRole("region", { name: "Samples" }).getByRole("button");
  await expect(chips).toHaveCount(3);
  for (const name of ["RAG or fine-tuning?", "SQLite vs PostgreSQL", "HTTP caching (with an injection attempt)"]) {
    await page.getByRole("button", { name }).click();
    await expect(page.getByText("Stored result — replay (0 AI calls)")).toBeVisible();
    await expect(finalAnswer(page)).toBeVisible({ timeout: 40_000 });
    await expect(page.getByRole("listitem", { name: "Writer: done" })).toBeVisible();
    if (name === "RAG or fine-tuning?") {
      // the stored real run used parallel workers
      await expect(page.getByRole("list", { name: "Transcript" }).getByText("These workers ran in parallel.")).toBeAttached();
    }
  }
  await expect(page.getByText(/prompt-injection attempts were found/)).toBeVisible();
  expect(posts).toEqual([]);
});

// E6 + E7 (mobile)
test("phone width: no horizontal scroll, tabs switch the panels", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 740 });
  await page.goto("/");
  await page.getByRole("button", { name: "RAG or fine-tuning?" }).click();
  await expect(finalAnswer(page)).toBeVisible({ timeout: 40_000 });
  await expectNoHorizontalScroll(page);
  await expect(page.getByRole("heading", { name: "Agents" })).toBeHidden();
  await page.getByRole("tab", { name: "Agents" }).click();
  await expect(page.getByRole("heading", { name: "Agents" })).toBeVisible();
  await expect(finalAnswer(page)).toBeHidden();
  await expectNoHorizontalScroll(page);
  await page.getByRole("tab", { name: "Transcript" }).click();
  await expect(page.getByRole("list", { name: "Transcript" })).toBeVisible();
  await expectNoHorizontalScroll(page);
  await expectAccessible(page);
});
