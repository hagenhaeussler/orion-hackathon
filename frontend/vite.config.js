import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: true,
    // Optimize for faster startup
    hmr: {
      overlay: false  // Disable error overlay for faster startup
    }
  },
  // Optimize build/dev performance
  optimizeDeps: {
    include: ['react', 'react-dom']
  }
})

