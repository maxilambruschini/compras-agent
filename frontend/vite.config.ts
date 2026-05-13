import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// REVIEWS.md MEDIUM fix: proxy target reads from env var so this config works
// both inside Docker (VITE_API_URL=http://backend:8000) and locally (fallback http://localhost:8000)
const apiTarget = process.env.VITE_API_URL || 'http://localhost:8000'

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
