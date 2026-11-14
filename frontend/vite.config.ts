import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The built app is served by web/ at /app/, so the demo needs no Node.
// In dev, /api goes to the web/ backend-for-frontend (default :8080; never to the trade server).
const apiTarget = process.env.API_TARGET ?? 'http://localhost:8080'

export default defineConfig({
  base: '/app/',
  plugins: [react(), tailwindcss()],
  resolve: {
    // Root-relative, not absolute: on Windows an absolute alias can differ in drive-letter
    // case ("C:" vs "c:") from the cwd, which bundled React and react-router twice.
    alias: [{ find: /^@\//, replacement: '/src/' }],
    dedupe: ['react', 'react-dom', 'react-router'],
  },
  server: {
    port: 5173,
    proxy: { '/api': { target: apiTarget, changeOrigin: true } },
  },
})
