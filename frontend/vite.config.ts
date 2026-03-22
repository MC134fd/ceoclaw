import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  publicDir: 'home',
  server: {
    port: 5173,
    proxy: {
      '/builder': 'http://localhost:8000',
      '/website': 'http://localhost:8000',
      '/websites': 'http://localhost:8000',
      '/health': 'http://localhost:8000',
      '/model': 'http://localhost:8000',
      '/runs': 'http://localhost:8000',
    }
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
  }
})
