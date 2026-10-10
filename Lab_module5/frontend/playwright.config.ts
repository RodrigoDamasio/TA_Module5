import { defineConfig, devices } from "@playwright/test";

// BASE_URL=https://<vercel-domain> runs the production subset (E8) instead of local servers.
const deployedUrl = process.env.BASE_URL;

export default defineConfig({
  testDir: "./e2e",
  timeout: 90_000,
  expect: { timeout: 20_000 },
  reporter: [["list"]],
  workers: 1, // one backend: runs execute one at a time
  use: {
    baseURL: deployedUrl ?? "http://localhost:3000",
    // Playwright's bundled Chromium is not supported on Ubuntu 20.04: use the installed Chrome.
    channel: "chrome",
    trace: "retain-on-failure",
  },
  projects: [{ name: "desktop", use: { ...devices["Desktop Chrome"], channel: "chrome" } }],
  webServer: deployedUrl
    ? undefined
    : [
        {
          // Real backend with the demo agents and built-in Wikipedia: the whole loop, 0 quota.
          // FAKE_LLM_DELAY_S makes the live agent board visibly change.
          command: "rm -rf .e2e && mkdir -p .e2e && ../../../.venv/bin/uvicorn app.main:app --port 8000",
          cwd: "../backend",
          url: "http://localhost:8000/health",
          env: {
            LLM_MODE: "fake",
            FAKE_LLM_DELAY_S: "0.3",
            DATABASE_PATH: ".e2e/research.db",
            FRONTEND_ORIGIN: "http://localhost:3000",
            RATE_LIMIT_RUNS_PER_MINUTE: "1000",
            RATE_LIMIT_RUNS_PER_DAY: "10000",
          },
          reuseExistingServer: false,
        },
        {
          // Production build: no file watchers (the dev server hits the OS watch limit here).
          command: "npm run build && npm run start",
          url: "http://localhost:3000",
          env: { NEXT_PUBLIC_API_URL: "http://localhost:8000" },
          timeout: 180_000,
          reuseExistingServer: false,
        },
      ],
});
