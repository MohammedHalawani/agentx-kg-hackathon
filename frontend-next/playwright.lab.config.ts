import { defineConfig } from "@playwright/test";
/**
 * Regression against the original UI lab: the unmodified lab specs run against this codebase
 * built in lab mode (browser fixtures). It proves the integrated screens still look and behave
 * like the standalone lab. The connected product is covered by playwright.config.ts.
 */
export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: false,
  workers: 1,
  timeout: 45000,
  outputDir: "test-results/lab",
  reporter: [["list"]],
  use: {
    baseURL: "http://127.0.0.1:5180",
    channel: "chrome",
    viewport: { width: 1440, height: 900 },
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  webServer: {
    command: "npm run dev:lab",
    url: "http://127.0.0.1:5180",
    reuseExistingServer: true,
    timeout: 30000,
  },
});
