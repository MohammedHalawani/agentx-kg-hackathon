import { defineConfig } from "@playwright/test";
/**
 * The connected product (the build the backend serves under /app/), driven against a
 * scripted stand-in for the backend's HTTP surface in the backend's own wire format.
 * The stand-in lives in the tests only. The original lab specs run from
 * playwright.lab.config.ts; a live backend is exercised by playwright.live.config.ts (the only real-HTTP evidence).
 */
export default defineConfig({
  testDir: "./tests/e2e-backend",
  fullyParallel: false,
  workers: 1,
  timeout: 45000,
  outputDir: "test-results/backend",
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: "http://127.0.0.1:5191",
    channel: "chrome",
    viewport: { width: 1440, height: 900 },
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  webServer: {
    command: "npm run build && npm run preview",
    url: "http://127.0.0.1:5191/app/",
    reuseExistingServer: true,
    timeout: 180000,
  },
});
