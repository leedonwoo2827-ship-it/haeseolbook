import { defineConfig } from '@playwright/test';

/**
 * 사전 준비 (README 참고)
 *   API: php -S localhost:8080 -t server/public server/public/index.php   (샘플 패키지 import 완료 상태)
 *   웹:  npm run dev:web   (VITE_API_URL=http://localhost:8080)
 */
export default defineConfig({
  testDir: '.',
  timeout: 60_000,
  workers: 1,
  use: { channel: process.env.PW_CHANNEL ?? 'chrome', baseURL: process.env.WEB_URL ?? 'http://localhost:5173', locale: 'ko-KR', trace: 'retain-on-failure' },
  reporter: [['list']],
});
