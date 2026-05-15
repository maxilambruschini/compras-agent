import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'path'

// Proxy target uses API_PROXY_TARGET (non-VITE_ prefix = server-side only, never injected
// into the browser bundle). VITE_API_URL is intentionally left unset so the browser-side
// BASE_URL resolves to "" and all API calls go through the Vite proxy on the same origin.
const apiTarget = process.env.API_PROXY_TARGET || 'http://localhost:8000'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    host: true,
    port: 5173,
    proxy: {
      '/api': apiTarget,
      '/health': apiTarget,
      '/invoices': apiTarget,
      '/images': apiTarget,
    },
  },
})
