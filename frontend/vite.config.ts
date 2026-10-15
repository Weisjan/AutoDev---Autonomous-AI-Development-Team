import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

const port = process.env.AUTODEV_API_PORT || "8000";
if (!/^\d{4,5}$/.test(port) || Number(port) > 65535)
  throw new Error("Invalid API port");
export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    allowedHosts: ["localhost"],
    proxy: { "/api": { target: `http://127.0.0.1:${port}` } },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test-setup.ts"],
    include: ["src/**/*.test.tsx"],
  },
});
