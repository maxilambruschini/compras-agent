import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Dev-proxy target — SERVER-SIDE ONLY. Read from a NON-VITE_ env var so it is never
// inlined into the browser bundle. Docker sets API_PROXY_TARGET=http://backend:8000;
// locally it falls back to http://localhost:8000. The browser always uses the relative
// "/api" base (see src/api/client.ts) and hits this proxy same-origin → no CORS.
// (Do NOT use a VITE_-prefixed var here: Vite exposes those to the browser, which would
// leak the Docker-internal hostname and cause the cross-origin/CORS failure this fixes.)
const apiTarget = process.env.API_PROXY_TARGET || 'http://localhost:8000'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 5173,
    proxy: {
      '/api': apiTarget,
      '/health': apiTarget,
    },
  },
})
