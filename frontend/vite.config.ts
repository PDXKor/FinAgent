/// <reference types="vitest/config" />
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv, type ProxyOptions } from "vite";

// Backends are reached through this same-origin proxy, which adds their bearer tokens.
// FINAGENT_* vars are read here only; the client bundle sees VITE_* vars, so tokens stay server-side.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "FINAGENT_");
  const backend = (prefix: string, target: string, token?: string): ProxyOptions => ({
    target,
    changeOrigin: true,
    rewrite: (path) => path.slice(prefix.length),
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
  });
  const proxy = {
    "/api/data": backend(
      "/api/data",
      env.FINAGENT_DATA_URL || "http://127.0.0.1:8765",
      env.FINAGENT_DATA_TOKEN,
    ),
    "/api/agents": backend(
      "/api/agents",
      env.FINAGENT_AGENTS_URL || "http://127.0.0.1:8766",
      env.FINAGENT_AGENTS_TOKEN,
    ),
  };
  return {
    plugins: [react(), tailwindcss()],
    server: { port: 5173, strictPort: true, proxy },
    preview: { proxy },
    test: { environment: "jsdom", globals: true, setupFiles: ["src/test/setup.ts"] },
  };
});
