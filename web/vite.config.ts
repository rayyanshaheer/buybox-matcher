/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: "./src/test/setup.ts",
    css: false,
    env: {
      // Provide the single permitted external reference for tests (Req 14.2).
      VITE_API_URL: "http://localhost:8000",
    },
  },
});
