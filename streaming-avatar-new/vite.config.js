// vite.config.js
import { defineConfig } from 'vite';

export default defineConfig({
  server: {
    host: '0.0.0.0', // Allow access from outside the instance
    port: 5173,      // Port to run the Vite server
  },
});
