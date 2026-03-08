import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // Proxy API calls to backend during development
      "/chat":   "http://localhost:8000",
      "/health": "http://localhost:8000",
      "/eda":    "http://localhost:8000",
      "/tables": "http://localhost:8000",
    },
  },
});
