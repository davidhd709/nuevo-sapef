/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import { VitePWA } from "vite-plugin-pwa";

// App de campo (PWA). Corre en su propio puerto; en producción se sirve en su subdominio con la
// API en el mismo origen (/api) para que las cookies de sesión viajen solas.
const api = { "/api": "http://127.0.0.1:8000" };

export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      // Service Worker propio (src/sw.ts) con Workbox: precarga, avisos push y la regla de no
      // actualizarse mientras haya trabajo sin enviar.
      strategies: "injectManifest",
      srcDir: "src",
      filename: "sw.ts",
      registerType: "prompt",
      injectRegister: false,
      manifest: {
        name: "SAPEF Campo",
        short_name: "SAPEF Campo",
        description: "Órdenes de trabajo de alumbrado público, con o sin señal",
        lang: "es",
        start_url: "/",
        scope: "/",
        display: "standalone",
        orientation: "portrait",
        background_color: "#ffffff",
        theme_color: "#f5b400",
        icons: [
          { src: "icono-192.png", sizes: "192x192", type: "image/png" },
          { src: "icono-512.png", sizes: "512x512", type: "image/png" },
          { src: "icono-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
        ],
      },
      injectManifest: {
        globPatterns: ["**/*.{js,css,html,png,svg,woff2}"],
        maximumFileSizeToCacheInBytes: 5 * 1024 * 1024,
      },
      devOptions: { enabled: true, type: "module", navigateFallback: "index.html" },
    }),
  ],
  // 127.0.0.1 explícito: en Windows "localhost" puede quedar solo en IPv6.
  server: { host: "127.0.0.1", port: 5174, strictPort: true, proxy: api },
  preview: { host: "127.0.0.1", port: 4174, strictPort: true, proxy: api },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/pruebas/preparar.ts"],
  },
});
