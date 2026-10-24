/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The production build is written into the Python package so `openpipeline serve`
// ships the UI with no separate web server.
//
// `vite build --mode demo` makes the hosted read-only demo instead: .env.demo sets
// VITE_DEMO=1, the app is served from /demo/, and the output goes to ./dist-demo unless
// --outDir says otherwise (scripts/build_site.sh does).
export default defineConfig(({ mode }) => ({
  plugins: [react()],
  base: mode === "demo" ? "/demo/" : "/",
  build: {
    outDir: mode === "demo" ? "dist-demo" : "../server/src/openpipeline/static",
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8484",
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    css: false,
  },
}));
