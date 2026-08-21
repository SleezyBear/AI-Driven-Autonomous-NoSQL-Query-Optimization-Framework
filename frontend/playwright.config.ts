import { defineConfig } from "playwright/test";

export default defineConfig({
  testDir: "./e2e",
  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL ?? "http://host.docker.internal:5173",
    browserName: "chromium",
  },
});
