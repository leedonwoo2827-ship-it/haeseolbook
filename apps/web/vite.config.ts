import { fileURLToPath, URL } from 'node:url';
import react from '@vitejs/plugin-react';
import { defineConfig, loadEnv } from 'vite';
import { VitePWA } from 'vite-plugin-pwa';

/**
 * 배포 경로(VITE_BASE)와 API 주소(VITE_API_URL)는 .env 로 정한다.
 *   출판사 사이트: VITE_BASE=/exam/ebook/  VITE_API_URL=/exam/ebook/api
 *   로컬 개발:     VITE_BASE=/            VITE_API_URL=http://localhost:8080
 */
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  const base = env.VITE_BASE || '/';
  return {
    base,
    resolve: {
      alias: { '@hsb/shared': fileURLToPath(new URL('../../packages/shared/src/index.ts', import.meta.url)) },
    },
    server: { port: 5173 },
    plugins: [
      react(),
      VitePWA({
        registerType: 'autoUpdate',
        includeAssets: ['icon.svg'],
        manifest: {
          name: '해설북 — 기출 해설영상 필기 이북',
          short_name: '해설북',
          description: '기술직 공무원 기출 원문 위에 필기하며 문항별 유튜브 해설을 보는 이북',
          lang: 'ko',
          start_url: base,
          scope: base,
          display: 'standalone',
          background_color: '#f6f7f9',
          theme_color: '#111827',
          icons: [
            { src: 'icon.svg', sizes: 'any', type: 'image/svg+xml', purpose: 'any' },
            { src: 'icon.svg', sizes: 'any', type: 'image/svg+xml', purpose: 'maskable' },
          ],
        },
        workbox: {
          navigateFallback: `${base}index.html`,
          navigateFallbackDenylist: [/\/api\//, /\/admin/],
          globPatterns: ['**/*.{js,css,html,svg,woff2}'],
          runtimeCaching: [
            {
              // 서명 URL 은 만료 시각(쿼리)이 바뀌므로 쿼리를 뗀 경로로 캐시해 오프라인에서도 열리게 한다
              urlPattern: ({ url }) => url.pathname.includes('/assets/books/'),
              handler: 'CacheFirst',
              options: {
                cacheName: 'hsb-pages',
                expiration: { maxEntries: 3000, maxAgeSeconds: 60 * 60 * 24 * 90 },
                cacheableResponse: { statuses: [200] },
                plugins: [{ cacheKeyWillBeUsed: async ({ request }) => request.url.split('?')[0] }],
              },
            },
          ],
        },
      }),
    ],
  };
});
