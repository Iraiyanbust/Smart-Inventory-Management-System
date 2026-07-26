import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        // Default 8010 avoids clashing with other Django apps commonly bound to 8000.
        target: process.env.VITE_BACKEND_TARGET || 'http://127.0.0.1:8010',
        changeOrigin: true,
      },
    },
  },
})
