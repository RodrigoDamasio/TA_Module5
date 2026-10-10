import AxeBuilder from "@axe-core/playwright";
import { expect, type Page } from "@playwright/test";

export const PROD = Boolean(process.env.BASE_URL);

/** No serious or critical axe violations (WCAG 2.x A/AA). */
export async function expectAccessible(page: Page) {
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
  const bad = results.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  expect(bad.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`)).toEqual([]);
}

export async function expectNoHorizontalScroll(page: Page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);
}

export async function sendTask(page: Page, task: string) {
  await page.getByLabel("Research task").fill(task);
  await page.getByRole("button", { name: "Send" }).click();
}

export const finalAnswer = (page: Page) => page.getByRole("article", { name: "Final answer" }).last();
