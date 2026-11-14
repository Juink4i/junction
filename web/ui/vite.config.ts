import path from "node:path"
import { defineConfig } from "vite"
import react from "@vitejs/plugin-react"
import tailwindcss from "@tailwindcss/vite"

// Five pages, each its own HTML file, built into web/static where the Python server
// (web/app.py) already serves them. `npm run dev` proxies /api to that server on :8080.
const pages = ["stage", "approvals", "log", "chat", "onboarding"]

export default defineConfig({
  plugins: [react(), tailwindcss()],
  base: "/static/",
  resolve: { alias: { "@": path.resolve(__dirname, "./src") } },
  build: {
    outDir: "../static",
    emptyOutDir: true,
    rollupOptions: {
      input: Object.fromEntries(pages.map((p) => [p, path.resolve(__dirname, `${p}.html`)])),
    },
  },
  server: {
    proxy: { "/api": { target: process.env.WEB_URL ?? "http://localhost:8080", changeOrigin: true } },
  },
})
