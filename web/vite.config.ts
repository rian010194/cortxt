import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()] as unknown as any,
  test: {
    environment: 'jsdom',
    globals: true,
  },
})
