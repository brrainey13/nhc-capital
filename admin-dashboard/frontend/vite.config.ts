import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react({
    babel: {
      plugins: ['babel-plugin-react-compiler'],
    },
  })],
  server: {
    port: 3000,
    allowedHosts: 'all',
    proxy: { '/api': 'http://localhost:8000' },
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          'react-vendor': ['react', 'react-dom'],
          'table-vendor': ['@tanstack/react-table', '@tanstack/react-virtual'],
          'chart-vendor': ['recharts'],
        },
      },
    },
  },
})
