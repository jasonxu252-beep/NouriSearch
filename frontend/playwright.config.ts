import { defineConfig, devices } from "@playwright/test";

// The tests drive the real page against the real API, with the USDA data loaded.
export default defineConfig({
  testDir: "e2e",
  fullyParallel: true,
  // More browsers than this stall on the development machine, even against a plain file server,
  // while the same requests from curl do not. Security software there is the likely cause.
  workers: 2,
  expect: { timeout: 10_000 },
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: "http://localhost:4173",
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: "npm run build && npm run preview",
    url: "http://localhost:4173",
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
