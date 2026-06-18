import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  base: './',
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/ingest': 'http://127.0.0.1:8000',
      '/query': 'http://127.0.0.1:8000',
      '/documents': 'http://127.0.0.1:8000',
      '/rules': 'http://127.0.0.1:8000',
      '/preprocess': 'http://127.0.0.1:8000',
      '/tags': 'http://127.0.0.1:8000',
      '/health': 'http://127.0.0.1:8000',
      '/version': 'http://127.0.0.1:8000',
      '/analytics': 'http://127.0.0.1:8000',
      '/taxonomy': 'http://127.0.0.1:8000',
    },
  },
})
