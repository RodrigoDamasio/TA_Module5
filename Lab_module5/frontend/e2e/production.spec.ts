import { expect, test } from "@playwright/test";
import { expectAccessible, finalAnswer, PROD, sendTask } from "./helpers";

test.skip(!PROD, "production only: BASE_URL=https://<vercel-domain> npm run test:e2e");

// E8: one real run against the live URLs. Same task and settings as the backend's post-deploy
// check X5 (approval on, memory off, 5 decisions): the server's response cache should answer
// every call, so this costs 0 Gemini calls (a few if the cache missed).
test("one real run with approval, end to end", async ({ page }) => {
  test.setTimeout(240_000);
  await page.goto("/");
  await expect(page.getByRole("region", { name: "Samples" })).toBeVisible();
  await page.getByText(/^Settings:/).click();
  await page.getByLabel("Require my approval before the final answer").check();
  await page.getByLabel("Use memory of earlier tasks").uncheck();
  await sendTask(page, "When should I use RAG instead of fine-tuning?");
  await expect(page.getByRole("heading", { name: "Your approval is needed" })).toBeVisible({ timeout: 180_000 });
  await expectAccessible(page);
  await page.getByRole("button", { name: "Approve" }).click();
  const answer = finalAnswer(page);
  await expect(answer).toBeVisible();
  await expect(answer.getByRole("region", { name: "Sources" })).toContainText("en.wikipedia.org");
  await expect(page.getByText(/AI \(Gemini\) · model gemini-3\.5-flash-lite · prompt v2/)).toBeVisible();
  const meta = await page.getByText(/AI \(Gemini\) · model/).textContent();
  test.info().annotations.push({ type: "meta", description: meta ?? "" });
});
