import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'

export default defineConfig({
  plugins: [
    react(),
    // Installable PWA. The manifest itself is a real file
    // (`public/manifest.webmanifest`) rather than generated here, so what the
    // browser is offered can be read without building.
    VitePWA({
      // A new service worker waits instead of taking over: it is only activated
      // when the user accepts the reload (src/components/PwaStatus.tsx), so a
      // half-typed form is never thrown away by an update.
      registerType: 'prompt',
      // Registration is done from React (useRegisterSW), not injected.
      injectRegister: false,
      manifest: false,
      workbox: {
        globPatterns: ['**/*.{js,css,html,svg,png,webmanifest,woff2}'],
        // SPA routes resolve to the shell; anything under /api/ must never be.
        navigateFallback: '/index.html',
        navigateFallbackDenylist: [/^\/api\//],
        cleanupOutdatedCaches: true,
        runtimeCaching: [
          {
            // Authenticated JSON. NetworkOnly, deliberately: a cached analysis
            // list or finding would be served after a token expired, and the
            // browser would have no way to tell it apart from live data.
            urlPattern: ({ url }) => url.pathname.startsWith('/api/'),
            handler: 'NetworkOnly',
          },
          {
            urlPattern: /^https:\/\/fonts\.googleapis\.com\/.*/i,
            handler: 'StaleWhileRevalidate',
            options: { cacheName: 'google-fonts-stylesheets' },
          },
          {
            urlPattern: /^https:\/\/fonts\.gstatic\.com\/.*/i,
            handler: 'CacheFirst',
            options: {
              cacheName: 'google-fonts-webfonts',
              expiration: { maxEntries: 8, maxAgeSeconds: 60 * 60 * 24 * 365 },
              cacheableResponse: { statuses: [0, 200] },
            },
          },
        ],
      },
      // Off in development: a service worker over the Vite dev server serves
      // stale bundles and hides every change behind a reload.
      devOptions: { enabled: false },
    }),
  ],
  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: 'http://localhost:8001',
        changeOrigin: true,
      },
    },
  },
  // `npm run preview` serves the real production build — the only way to see the
  // service worker locally — so it needs the same proxy to reach a local API.
  preview: {
    port: 4173,
    proxy: {
      '/api': {
        target: 'http://localhost:8001',
        changeOrigin: true,
      },
    },
  },
})
