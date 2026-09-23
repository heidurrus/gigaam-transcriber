import { defineConfig } from "vite";
import { svelte } from "@sveltejs/vite-plugin-svelte";

// Built into static/app and served by Flask at "/". The build output is committed,
// so running the app from source or packaging it doesn't need Node.
export default defineConfig({
  plugins: [svelte()],
  base: "/static/app/",
  build: { outDir: "../static/app", emptyOutDir: true, assetsDir: "assets", sourcemap: false },
  server: {
    // `npm run dev` proxies API calls to a running app (WORKBENCH_PORT, default 47823).
    proxy: Object.fromEntries(["/api", "/transcribe", "/job", "/summarize", "/settings", "/health",
      "/models", "/device-info", "/audio-devices", "/desktop-record", "/ollama", "/__workbench"]
      .map(p => [p, `http://127.0.0.1:${process.env.WORKBENCH_PORT || 47823}`])),
  },
});
