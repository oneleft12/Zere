import { defineConfig } from "vite";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

// Dev-режим: vite dev-сервер проксирует /api на локальный бэкенд ZERE,
// подставляя токен из config/panel.token — UI в dev шлёт плейсхолдер.
function panelToken(): string {
  try {
    return readFileSync(resolve(import.meta.dirname, "../config/panel.token"), "utf8").trim();
  } catch {
    return "";
  }
}

export default defineConfig({
  build: {
    outDir: "dist",
    emptyOutDir: true,
    sourcemap: false,
  },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8080",
        changeOrigin: false,
        headers: { "X-ZERE-Token": panelToken() },
      },
    },
  },
});
