import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    // Proxy /api to the FastAPI backend during development. This is the
    // idiomatic Vite setup and is better than relying on CORS: to the
    // browser every request is same-origin, so there is no preflight and
    // no cross-origin exposure at all. The backend's CORS middleware is
    // still there as a fallback for running the dev server without this
    // proxy, but this path never needs it.
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
})
