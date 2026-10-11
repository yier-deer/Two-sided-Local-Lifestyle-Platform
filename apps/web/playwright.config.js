import { defineConfig } from "@playwright/test";
import { existsSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { homedir } from "node:os";

const browserCache = process.env.LOCALAPPDATA
  ? join(process.env.LOCALAPPDATA, "ms-playwright")
  : join(homedir(), ".cache", "ms-playwright");
const cached = existsSync(browserCache)
  ? readdirSync(browserCache)
      .filter((n) => /^chromium-\d+$/.test(n))
      .sort((a, b) => Number(b.split("-")[1]) - Number(a.split("-")[1]))
  : [];
const browserCandidates = cached.flatMap((n) => [
  join(browserCache, n, "chrome-win64", "chrome.exe"),
  join(browserCache, n, "chrome-win", "chrome.exe"),
  join(browserCache, n, "chrome-linux", "chrome"),
]);
const executablePath =
  process.env.SCOUTBITE_BROWSER_BINARY || browserCandidates.find(existsSync);
export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 60000,
  expect: { timeout: 10000 },
  workers: 1,
  reporter: "list",
  use: {
    baseURL: "http://127.0.0.1:5173",
    viewport: { width: 1440, height: 1000 },
    launchOptions: executablePath ? { executablePath } : {},
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  webServer: {
    command: "npm run dev -- --host 127.0.0.1",
    url: "http://127.0.0.1:5173",
    reuseExistingServer: !process.env.CI,
    timeout: 60000,
  },
});
