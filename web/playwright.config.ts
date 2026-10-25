import { defineConfig, devices } from "@playwright/test";

// Drives the built app served by the API (replay mode when no keys are set):
//   npm run build && npx playwright test
const port = Number(process.env.HP_PORT ?? 8000);
const python = process.env.HP_PYTHON ?? "python";

export default defineConfig({
  testDir: "e2e",
  timeout: 90_000,
  workers: 1,
  reporter: [["list"], ["json", { outputFile: "test-results/report.json" }]],
  use: { baseURL: `http://localhost:${port}` },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"], viewport: { width: 1360, height: 900 }, deviceScaleFactor: 2 }, grepInvert: /@phone/ },
    { name: "phone", use: { ...devices["Pixel 7"] }, grep: /@phone/ },
  ],
  webServer: process.env.HP_NO_SERVER ? undefined : {
    command: `${python} -m uvicorn handpicked.app:app --port ${port}`,
    cwd: "..",
    url: `http://localhost:${port}/api/health`,
    reuseExistingServer: true,
    timeout: 120_000,
  },
});
