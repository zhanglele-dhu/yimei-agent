import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

const outputDir = process.env.NETLIFY === 'true'
  ? 'dist'
  : fileURLToPath(new URL('../studio/static/vue-app', import.meta.url))

export default defineConfig({
  plugins: [vue()],
  base: './',
  build: {
    outDir: outputDir,
    emptyOutDir: true
  },
  server: {
    proxy: { '/api': 'http://127.0.0.1:8010' }
  }
})
