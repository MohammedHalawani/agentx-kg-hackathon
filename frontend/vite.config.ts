import path from 'node:path'
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// @neo4j-nvl/react ships react as a hard dependency (not a peer), so without dedupe the bundle
// gets two React copies → "invalid hook call". Force the single top-level one. There is no dev
// server: the built bundle is served by the FastAPI backend (one origin, one mode: production).
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    dedupe: ['react', 'react-dom'],
    alias: { '@': path.resolve(__dirname, './src') },
  },
  // unit tests (vitest): jsdom for component rendering, globals so testing-library auto-cleans up,
  // a setup file to stub matchMedia (motion needs it under jsdom)
  test: { environment: 'jsdom', globals: true, setupFiles: ['./src/test/setup.ts'] },
})
