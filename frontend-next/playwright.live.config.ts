import { defineConfig } from "@playwright/test";
/**
 * Checks against a running Suhail backend that serves this app under /app/:
 *   SUHAIL_LIVE_URL=http://127.0.0.1:8000 npx playwright test --config playwright.live.config.ts
 * By default the specs only read. With SUHAIL_LIVE_WRITE=1 (scratch database only) the
 * walkthrough also makes real operator requests: investigate, reject, escalate, approve,
 * worker start and pause. No spec ever makes a model call on its own.
 */
export default defineConfig({
  testDir: "./tests/e2e-live",
  fullyParallel: false,
  workers: 1,
  timeout: 60000,
  outputDir: "test-results/live",
  reporter: [["list"]],
  use: {
    baseURL: process.env.SUHAIL_LIVE_URL ?? "http://127.0.0.1:8000",
    channel: "chrome",
    viewport: { width: 1440, height: 900 },
    screenshot: "only-on-failure",
  },
});
