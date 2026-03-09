import path from 'path'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [tailwindcss(), react({
    babel: {
      plugins: ['babel-plugin-react-compiler'],
    },
  })],
  server: {
    port: 3000,
    allowedHosts: 'all',
    proxy: { '/api': 'http://localhost:8000' },
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
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
