import { expect, test, type Browser, type Page } from '@playwright/test';

const SHOTS = process.env.SHOT_DIR;
const IPAD_UA = 'Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1';
const email = `e2e-${Date.now()}@test.kr`;

async function login(page: Page) {
  await page.goto('/');
  await page.getByText('샘플 전기이론 (시험용)').first().click();
  await expect(page).toHaveURL(/\/login/);
  await page.getByPlaceholder('you@example.com').fill(email);
  await page.getByRole('button', { name: '이메일로 로그인' }).click();
  await expect(page).toHaveURL(/\/read\/sample-electric/);
  await expect(page.locator('.page img').first()).toBeVisible();
}

/** 페이지 1 필기 캔버스에 칠해진 픽셀 수 */
async function inkPixels(page: Page, index = 0) {
  return page.locator('.page canvas.ink:not(.live)').nth(index).evaluate((c: HTMLCanvasElement) => {
    const d = c.getContext('2d')!.getImageData(0, 0, c.width, c.height).data;
    let n = 0;
    for (let i = 3; i < d.length; i += 4) if (d[i] > 0) n++;
    return n;
  });
}

async function drawZigzag(page: Page, fx: number, fy: number) {
  // 그릴 위치를 원문 스크롤 영역의 가운데로 가져온다 (태블릿·폰은 위쪽에 영상·도구 막대가 있음)
  const area = (await page.locator('.pages').boundingBox())!;
  let box = (await page.locator('.page canvas.live').first().boundingBox())!;
  const target = box.y + box.height * fy;
  if (target < area.y + 40 || target > area.y + area.height - 40) {
    await page.locator('.pages').evaluate((el, dy) => el.scrollBy(0, dy), target - (area.y + area.height / 2));
    await page.waitForTimeout(100);
    box = (await page.locator('.page canvas.live').first().boundingBox())!;
  }
  const x = box.x + box.width * fx;
  const y = box.y + box.height * fy;
  await page.mouse.move(x, y);
  await page.mouse.down();
  for (let i = 1; i <= 12; i++) await page.mouse.move(x + i * 12, y + (i % 2 ? 14 : 0), { steps: 2 });
  await page.mouse.up();
}

async function newDevice(browser: Browser, opts: Parameters<Browser['newContext']>[0]) {
  const ctx = await browser.newContext(opts);
  return { ctx, page: await ctx.newPage() };
}

test('pc: login → read → draw → grade → sync to tablet', async ({ browser }) => {
  const pc = await newDevice(browser, { viewport: { width: 1440, height: 900 } });
  await login(pc.page);

  // 원문 이미지 로드 (서명 URL)
  await expect.poll(() => pc.page.locator('.page img').first().evaluate((img: HTMLImageElement) => img.complete && img.naturalWidth > 0), { timeout: 10_000 }).toBe(true);

  // 펜으로 필기 → 서버 저장
  await pc.page.getByRole('button', { name: '펜', exact: true }).click();
  expect(await inkPixels(pc.page)).toBe(0);
  await drawZigzag(pc.page, 0.2, 0.32);
  expect(await inkPixels(pc.page)).toBeGreaterThan(200);
  await expect(pc.page.locator('.sync')).toHaveText('저장됨', { timeout: 10_000 });

  // 실행 취소 / 다시 실행
  await pc.page.getByRole('button', { name: '실행 취소' }).click();
  expect(await inkPixels(pc.page)).toBe(0);
  await pc.page.getByRole('button', { name: '다시 실행' }).click();
  expect(await inkPixels(pc.page)).toBeGreaterThan(200);

  // 문항 선택 → 오답 → 해설(수식) → 정답
  await pc.page.locator('.qno', { hasText: /^1/ }).click();
  await pc.page.getByRole('button', { name: '1번 보기 선택' }).click();
  await expect(pc.page.locator('.verdict')).toHaveText(/오답 — 정답은 ②/);
  await expect(pc.page.locator('.solution .katex').first()).toBeVisible();
  await pc.page.getByRole('button', { name: '2번 보기 선택' }).click();
  await expect(pc.page.locator('.verdict')).toHaveText('정답입니다');
  await pc.page.getByRole('tab', { name: /오답노트/ }).click();
  await expect(pc.page.locator('.notes')).toContainText('1번');
  await expect(pc.page.locator('.notes')).toContainText('다시 풀어 맞힘');
  if (SHOTS) await pc.page.screenshot({ path: `${SHOTS}/pc.png` });

  // 영상 패널 폭: 기본 = 화면의 36%, 경계를 끌면 넓어지고 새로고침해도 유지
  const sideW = () => pc.page.locator('.side').evaluate((el) => el.getBoundingClientRect().width);
  expect(Math.round(await sideW())).toBe(Math.round(1440 * 0.36));
  const sp = (await pc.page.locator('.splitter').boundingBox())!;
  await pc.page.mouse.move(sp.x + sp.width / 2, sp.y + sp.height / 2);
  await pc.page.mouse.down();
  await pc.page.mouse.move(800, sp.y + sp.height / 2, { steps: 5 });
  await pc.page.mouse.up();
  expect(Math.abs((await sideW()) - 800)).toBeLessThan(8);
  await pc.page.locator('.splitter').dblclick();
  expect(Math.round(await sideW())).toBe(Math.round(1440 * 0.36));

  // 보기 모드에서 문항 영역 탭 → 해당 문항 선택
  await pc.page.getByRole('tab', { name: '문항·해설' }).click();
  await pc.page.getByRole('button', { name: '보기', exact: true }).click();
  const box = (await pc.page.locator('.page canvas.live').first().boundingBox())!;
  await pc.page.mouse.click(box.x + box.width * 0.75, box.y + box.height * 0.6); // 오른쪽 단 아래 = 4번
  await expect(pc.page.locator('.quiz-head b')).toHaveText('4번');

  // 태블릿(다른 기기 유형)에서 같은 계정 → 필기가 보인다
  const tab = await newDevice(browser, { viewport: { width: 820, height: 1180 }, userAgent: IPAD_UA, hasTouch: true });
  await login(tab.page);
  await expect.poll(() => inkPixels(tab.page), { timeout: 10_000 }).toBeGreaterThan(200);
  if (SHOTS) await tab.page.screenshot({ path: `${SHOTS}/tablet.png` });

  // 태블릿에서도 쓰면 PC 가 30초 폴링 전이라도 새로고침 시 둘 다 보인다
  await tab.page.getByRole('button', { name: '펜', exact: true }).click();
  await drawZigzag(tab.page, 0.2, 0.7);
  await expect(tab.page.locator('.sync')).toHaveText('저장됨', { timeout: 10_000 });
  await pc.page.reload();
  await expect.poll(() => inkPixels(pc.page), { timeout: 10_000 }).toBeGreaterThan(400);

  await pc.ctx.close();
  await tab.ctx.close();
});

test('phone: offline drawing is kept and synced when back online', async ({ browser }) => {
  const phone = await newDevice(browser, { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true,
    userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1' });
  await login(phone.page);
  if (SHOTS) await phone.page.screenshot({ path: `${SHOTS}/phone.png` });
  await expect.poll(() => inkPixels(phone.page), { timeout: 10_000 }).toBeGreaterThan(200); // 같은 계정의 이전 필기

  await phone.ctx.setOffline(true);
  await phone.page.evaluate(() => window.dispatchEvent(new Event('offline')));
  await phone.page.getByRole('button', { name: '펜', exact: true }).click();
  await drawZigzag(phone.page, 0.55, 0.3);
  await expect(phone.page.locator('.sync')).toHaveText(/오프라인/, { timeout: 10_000 });

  await phone.ctx.setOffline(false);
  await phone.page.evaluate(() => window.dispatchEvent(new Event('online')));
  await expect(phone.page.locator('.sync')).toHaveText('저장됨', { timeout: 15_000 });
  await phone.ctx.close();
});
