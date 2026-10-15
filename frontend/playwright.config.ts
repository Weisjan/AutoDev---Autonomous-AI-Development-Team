import { defineConfig } from "@playwright/test";
import path from "node:path";

const python =
  process.env.AUTODEV_TEST_PYTHON ||
  (process.platform === "win32" ? "../.venv/Scripts/python.exe" : "python");
export default defineConfig({
  testDir: "./e2e",
  workers: 1,
  timeout: 45000,
  use: { baseURL: "http://127.0.0.1:5173", trace: "retain-on-failure" },
  webServer: [
    {
      command: `"${python}" ../tests/web_smoke_server.py`,
      url: "http://127.0.0.1:8001/api/health",
      timeout: 30000,
      reuseExistingServer: false,
    },
    {
      command: `"${process.execPath}" "${path.resolve("node_modules/vite/bin/vite.js")}" --host 127.0.0.1 --port 5173 --strictPort`,
      url: "http://127.0.0.1:5173",
      env: { AUTODEV_API_PORT: "8001" },
      timeout: 30000,
      reuseExistingServer: false,
    },
  ],
});
