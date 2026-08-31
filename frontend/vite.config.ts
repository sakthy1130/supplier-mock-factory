import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5144,
    proxy: {
      '/health': 'http://localhost:8001',
      '/api': 'http://localhost:8001',
      '/docs': 'http://localhost:8001',
      '/openapi.json': 'http://localhost:8001',
    },
  },
})
