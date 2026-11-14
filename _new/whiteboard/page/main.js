// 화이트보드 강의 한 섹션 — scene.json(언제 쓰는가) → 배치(어디에 쓰는가) → wb.js 타임라인·카메라·보드.
//   보드 한 장, 컷 없음: 슬라이드 하나 = 보드의 영역 하나(뱀 모양 격자), 장 경계의 꼬리(0.45초)에 카메라가 옆 영역으로 간다.
//   펜·손·커서는 그리지 않는다(강의평: 펜 모양이 정신없다). 잉크와 소리만.
//   window: DUR · EV(소리 이벤트) · STILLS · render(t) · sig(t)(정지 프레임 재사용 키) · READY
import * as W from './engine/wb.js';
import { htext, FONT, wrap, measure } from './engine/hangul.js';
import { svgToStrokes, tableToStrokes, C } from './engine/svgwb.js';
import { mulberry, clamp } from './engine/lib.js';

const q = new URLSearchParams(location.search);
const S = await (await fetch(q.get('scene') || 'scene.json')).json();
await document.fonts.load(`60px ${FONT}`, '가나다ABC123');
const FPS = +(q.get('fps') || 30);
const CIRCLED = '①②③④⑤⑥⑦⑧⑨';

// ───────────── 보드 격자
const SW = 2400, SH = 1500, GX = 320, GY = 280;
const N = S.slides.length;
const COLS = Math.max(2, Math.min(5, Math.round(Math.sqrt(N * 1.15))));
const ROWS = Math.ceil(N / COLS);
const BW = GX * 2 + COLS * SW, BH = GY * 2 + ROWS * SH;
const slot = i => { const r = Math.floor(i / COLS); let c = i % COLS; if (r % 2) c = COLS - 1 - c; return [GX + c * SW + SW / 2, GY + r * SH + SH / 2]; };
const frameOf = (i, z) => { const [cx, cy] = slot(i); const w = 1920 / z, h = 1080 / z; return { x: cx - w / 2, y: cy - h / 2, w, h, z, m: 120 / z, top: 92 / z, cx, cy }; };
const SAFE = .86;                                   // 아래 14% 는 자막 자리로 비운다

// ───────────── 배치 → 쓰기 작업(jobs)
const wd = (sh, k = 1) => clamp(.082 * sh.length * k, .35, 3.4);
const dot = (x, y, col, w = 15) => W.poly([x, y, x + 1, y + 1], { color: col, w });
const under = (x, y, w, col) => W.curve([[x - 6, y + 2], [x + w * .5, y + 7], [x + w + 16, y - 3]], { color: col, w: 8 });

function head(F, sl, label, L) {
  let y = F.y + F.top;
  if (label) { const g = htext(label, F.x + F.m, y + 40, { h: 46, color: C.blue }); L.push({ sh: g, at: sl.t0 + .05, dur: .6 }); y += 46 + 30; }
  return y;
}
function title(F, sl, y, L, k, accent) {
  const x0 = F.x + F.m, maxW = F.w - 2 * F.m, h = 104 * k;
  const tt = htext(sl.title, x0, y + h * .8, { h, maxW, color: C.ink, bold: true });
  const d = wd(tt, .85); L.push({ sh: tt, at: sl.title_at, dur: d });
  y += tt.height + 16;
  L.push({ sh: [under(x0, y, Math.min(tt.width, maxW), accent)], at: sl.title_at + d + .05, dur: .35 });
  return y + 56 * k;
}

function layNormal(sl, F, k) {
  const L = [], x0 = F.x + F.m, maxW = F.w - 2 * F.m, bottom = F.y + F.h * SAFE;
  let y = head(F, sl, sl.group, L);
  const ans = sl.kind === 'answer';
  y = title(F, sl, y, L, k, ans ? C.blue : C.acc);
  const bh = 70 * k, bl = sl.bullets || [];
  const layB = (y, bw) => {
    const out = [];
    bl.forEach((b, i) => {
      const col = ans && i === 0 ? C.acc : C.ink;
      const sh = htext(b.text, x0 + 50 * k, y + bh * .8, { h: bh, maxW: bw - 50 * k, color: col });
      out.push({ sh: [dot(x0 + 16 * k, y + bh * .45, C.blue, 15 * k), ...sh], at: b.at, dur: wd(sh) });
      y += sh.height + bh * .62;
    });
    return { out, y };
  };
  let B = layB(y, maxW), figBox = null;
  if (sl.fig) {                                     // 그림은 아래·오른쪽 중 더 크게 들어가는 쪽
    const vb = (sl.fig.src.match(/viewBox="([^"]+)"/) || [, '0 0 520 190'])[1].split(/[\s,]+/).map(Number);
    const below = { x: x0, y: B.y + 10, w: maxW, h: Math.max(160, bottom - B.y - 24) };
    const B2 = layB(y, maxW * .45), side = { x: x0 + maxW * .48, y: y - 10, w: maxW * .52, h: bottom - y };
    const sc = b => Math.min(b.w / vb[2], b.h / vb[3]);
    if (sl.fig.type === 'svg' && bl.length && B2.y <= bottom && sc(side) > sc(below) * 1.12) { B = B2; figBox = side; }
    else figBox = below;
  }
  L.push(...B.out);
  let end = B.y;
  if (sl.fig) {
    const r = sl.fig.type === 'table' ? tableToStrokes(sl.fig.src, figBox) : svgToStrokes(sl.fig.src, figBox);
    const sh = r.items.flatMap(it => it.shapes);
    if (sh.length) L.push({ sh, at: sl.fig.at, dur: clamp(.07 * sh.length, 2.4, 9) });
    end = Math.max(end, r.y + r.h);
  }
  return { L, end, bottom };
}

function layQuiz(sl, F, k) {
  const L = [], x0 = F.x + F.m, maxW = F.w - 2 * F.m, bottom = F.y + F.h * SAFE, cd = sl.card;
  let y = head(F, sl, cd.head || sl.group, L);
  const h0 = 64 * k, tt = htext(sl.title, x0, y + h0 * .8, { h: h0, maxW, color: C.ink, bold: true });
  L.push({ sh: tt, at: sl.title_at, dur: wd(tt, .8) }); y += tt.height + 34 * k;
  if (cd.q) { const qh = 50 * k, qs = htext(cd.q, x0, y + qh * .8, { h: qh, maxW, color: C.ink }); L.push({ sh: qs, at: cd.q_at, dur: wd(qs, .8) }); y += qs.height + 26 * k; }
  if (cd.passage.length) {
    const py0 = y; y += 22 * k; const px = x0 + 40 * k, pw = maxW - 80 * k;
    for (const p of cd.passage) {
      if (p.type === 'p') { const ph = 40 * k, s = htext(p.src, px, y + ph * .8, { h: ph, maxW: pw, color: C.ink }); L.push({ sh: s, at: p.at, dur: wd(s, .7) }); y += s.height + 14 * k; }
      else if (p.type === 'pre') {
        const ph = 36 * k, sh = []; for (const ln of p.src.split('\n')) { sh.push(...htext(ln.replace(/\t/g, '    '), px, y + ph * .8, { h: ph, color: C.ink })); y += ph * 1.25; }
        L.push({ sh, at: p.at, dur: wd(sh, .6) }); y += 8 * k;
      } else {
        const box = { x: px, y, w: Math.min(pw, 1500), h: 400 * k };
        const r = p.type === 'table' ? tableToStrokes(p.src, box) : svgToStrokes(p.src, box);
        const sh = r.items.flatMap(it => it.shapes); if (sh.length) L.push({ sh, at: p.at, dur: clamp(.06 * sh.length, 2, 7) });
        y = r.y + r.h + 18 * k;
      }
    }
    y += 10 * k;
    L.push({ sh: [W.roundRect(x0, py0, maxW, y - py0, 26, { color: C.blue, w: 5, alpha: .5 })], at: cd.passage[0].at - .25, dur: .45 });
    y += 30 * k;
  }
  const boxes = [];
  cd.choices.forEach((c, i) => {
    const ch = 46 * k, s = htext(`${CIRCLED[i] || i + 1} ${c.text}`, x0, y + ch * .8, { h: ch, maxW, color: C.ink });
    L.push({ sh: s, at: c.at, dur: wd(s, .75) });
    boxes.push([x0, y - 4, x0 + s.width, y + s.height + 4]); y += s.height + 20 * k;
  });
  return { L, end: y, bottom, boxes };
}

function layCover(sl, F) {
  const L = [], cx = F.x + F.w / 2, cv = sl.cover; let y = F.y + 300;
  const lb = htext(cv.label, cx, y, { h: 48, color: C.blue, align: 'center' }); L.push({ sh: lb, at: sl.t0 + .2, dur: wd(lb, .8) }); y += 150;
  const bg = htext(cv.big, cx, y, { h: 124, color: C.ink, align: 'center', maxW: 1560, bold: true });
  const d = wd(bg, 1.1); L.push({ sh: bg, at: sl.t0 + .9, dur: d }); y += bg.height - 124 + 34;
  L.push({ sh: [under(cx - Math.min(bg.width, 1560) / 2, y, Math.min(bg.width, 1560), C.acc)], at: sl.t0 + .9 + d + .05, dur: .4 }); y += 110;
  cv.items.forEach((it, i) => { const s = htext(it, cx, y, { h: 56, color: C.ink, align: 'center' }); L.push({ sh: s, at: cv.items_at[i], dur: wd(s) }); y += 84; });
  return { L, end: y, bottom: F.y + F.h * SAFE };
}

function layClosing(sl, F) {
  const L = [], x0 = F.x + F.m + 80; let y = F.y + 210;
  const tt = htext(sl.title, x0, y, { h: 96, color: C.ink, bold: true }); const d = wd(tt);
  L.push({ sh: tt, at: sl.title_at, dur: d }); L.push({ sh: [under(x0, y + 26, tt.width, C.acc)], at: sl.title_at + d + .05, dur: .3 }); y += 130;
  for (const b of sl.bullets || []) {
    const s = htext(b.text, x0 + 70, y + 50, { h: 66, color: C.ink, maxW: F.w - 2 * F.m - 160 });
    const ck = W.poly([x0 + 6, y + 20, x0 + 22, y + 40, x0 + 50, y - 4], { color: C.blue, w: 9 });
    L.push({ sh: [ck, ...s], at: b.at, dur: wd(s) }); y += s.height + 34;
  }
  return { L, end: y, bottom: F.y + F.h * SAFE };
}

// 넘치면 글자를 줄이고, 그래도 넘치면 카메라를 물린다(기출 카드처럼 많은 장)
function fit(i, sl) {
  if (sl.kind === 'cover') return { F: frameOf(i, 1), ...layCover(sl, frameOf(i, 1)) };
  if (sl.kind === 'closing') return { F: frameOf(i, 1), ...layClosing(sl, frameOf(i, 1)) };
  const lay = sl.kind === 'quiz' ? layQuiz : layNormal;
  let best = null;
  for (const z of [1, .92, .84, .76, .68, .62]) {
    for (const k of (z === 1 ? [1.2, 1.1, 1, .92, .85] : [1, .9])) {   // 내용이 적은 장은 글씨를 키운다
      const F = frameOf(i, z), r = lay(sl, F, k);
      best = { F, ...r };
      if (r.end <= r.bottom) return best;
    }
    if (sl.kind !== 'quiz' && z <= .84) break;      // 일반 장은 너무 물리지 않는다
  }
  return best;
}

const laid = S.slides.map((sl, i) => fit(i, sl));

// ───────────── 카메라: 장마다 머무는 자리(stops) → 키
const fullZ = Math.min(1920 / BW, 1080 / BH) * .92, FULL = [BW / 2, BH / 2, fullZ];
const stops = [];
let lastQuiz = -1;
const extra = [];                                   // 정답 장의 되짚기 동그라미
S.slides.forEach((sl, i) => {
  const F = laid[i].F, t0 = sl.t0, t1 = sl.t1;
  const arrive = i === 0 ? 1.0 : t0 + .2, depart = Math.max(arrive + .1, t1 - .4);
  if (sl.kind === 'answer' && lastQuiz >= 0 && sl.answer && laid[lastQuiz].boxes?.[sl.answer - 1]) {
    const Q = laid[lastQuiz].F, [a, b, c, d] = laid[lastQuiz].boxes[sl.answer - 1];
    const cx = (a + c) / 2, cy = (b + d) / 2, rx = (c - a) / 2 + 30, ry = (d - b) / 2 + 14;
    extra.push({ sh: [W.circle(cx, cy, rx, { ry, color: C.acc, w: 10, lap: .3 }), W.circle(cx + 4, cy - 3, rx * 1.02, { ry: ry * 1.06, color: C.acc, w: 8, lap: .25, a0: -2.0 })], at: t0 + .35, dur: 1.0, si: i, zone: 0 });
    stops.push({ x: Q.cx, y: Q.cy, z: Q.z, from: t0 + .15, to: t0 + 2.3, si: i, zone: 0 });
    stops.push({ x: F.cx, y: F.cy, z: F.z, from: t0 + 3.0, to: depart, si: i, zone: 1 });
  } else if (sl.kind === 'closing' && S.last) {
    const tp = Math.max(arrive + 2.5, t0 + Math.min(sl.speech * .55, sl.speech - 4));
    stops.push({ x: F.cx, y: F.cy, z: F.z, from: arrive, to: tp, si: i, zone: 1 });
    stops.push({ x: FULL[0], y: FULL[1], z: FULL[2], from: tp + 3.2, to: t1 + 1, si: i, zone: 2 });
  } else stops.push({ x: F.cx, y: F.cy, z: F.z, from: arrive, to: depart, si: i, zone: 1 });
  if (sl.kind === 'quiz') lastQuiz = i;
});
const keys = [[0, stops[0].x, stops[0].y, stops[0].z * .9, 0]];
let prevTo = 0;
for (const s of stops) {
  const from = Math.max(s.from, prevTo + .25);
  keys.push([from, s.x, s.y, s.z, 0, 'io'], [Math.max(from + .01, s.to), s.x, s.y, s.z, 0, 'l']);
  prevTo = Math.max(from + .01, s.to);
}
const cam = new W.Camera(keys);
const zoneArrive = (si, zone) => { const s = stops.find(s => s.si === si && s.zone === zone) || stops.find(s => s.si === si); return s ? s.from : 0; };

// ───────────── 쓰기 일정
const tl = new W.Timeline();
const jobs = [...extra];
laid.forEach((r, i) => r.L.forEach(j => jobs.push({ ...j, si: i, zone: 1 })));
jobs.forEach(j => { j.start = Math.max(j.at, zoneArrive(j.si, j.zone) + .05); });
jobs.sort((a, b) => a.start - b.start);
jobs.forEach((j, n) => {
  const sl = S.slides[j.si], nx = jobs[n + 1];
  let by = j.start + j.dur;
  if (nx && nx.start > j.start + .3) by = Math.min(by, nx.start - .04);
  by = Math.min(by, sl.t1 - .3);
  by = Math.max(by, j.start + .25);
  tl.draw(new W.Pen('p' + n, C.ink), j.sh, j.start, { by });
});
tl.end();

// ───────────── 보드(지난 수업의 흔적은 영역 가장자리·통로에만 옅게)
const R = mulberry(7), ghosts = [];
for (let k = 0; k < N * 3; k++) {
  const [cx, cy] = slot(Math.floor(R() * N)), side = R();
  const x = side < .5 ? cx + (R() < .5 ? -1 : 1) * (1000 + R() * 180) : cx + (R() - .5) * 1900;
  const y = side < .5 ? cy + (R() - .5) * 1100 : cy + (R() < .5 ? -1 : 1) * (600 + R() * 110);
  const col = R() < .7 ? '#8f98a3' : '#8aa4c8', al = .05 + R() * .04, f = R();
  const g = f < .3 ? [W.circle(x, y, 50 + R() * 110, { color: col, w: 8 })]
    : f < .55 ? W.arrow(x, y, x + (R() - .5) * 500, y + (R() - .5) * 260, { color: col, w: 8 })
    : f < .8 ? [W.curve([[x, y], [x + 120, y - 60 + R() * 120], [x + 260, y + (R() - .5) * 80], [x + 380, y]], { color: col, w: 8 })]
    : W.rect(x, y, 160 + R() * 220, 90 + R() * 120, { color: col, w: 7 });
  for (const s of g) { s.alpha = al; s.color = col; ghosts.push(s); }
}
const board = new W.Board(tl, { W: BW, H: BH, ghosts });

// 자막 굽기(선택): 흰 라벨 + 짧은 주황 마커 줄, 손글씨체
const SUBS = S.subs || [];
const subAt = t => { let lo = 0, hi = SUBS.length - 1, r = -1; while (lo <= hi) { const m = (lo + hi) >> 1; if (SUBS[m].a <= t) { r = m; lo = m + 1; } else hi = m - 1; } return r >= 0 && t < SUBS[r].b ? r : -1; };
if (q.get('burn') === '1') board.overlays.push({
  draw(ctx, t) {
    const i = subAt(t); if (i < 0) return;
    const h = 46, lines = wrap(SUBS[i].text.replace(/\n/g, ' '), h, 1500).slice(0, 2);
    const w = Math.max(...lines.map(l => measure(l, h))) + 90, H = lines.length * h * 1.25 + 30, x = 960 - w / 2, y = 1080 - 34 - H;
    ctx.fillStyle = 'rgba(252,251,247,.92)'; ctx.beginPath(); ctx.roundRect(x, y, w, H, 18); ctx.fill();
    ctx.fillStyle = C.acc; ctx.fillRect(x + 24, y + H / 2 - 3, 22, 6);
    ctx.fillStyle = C.ink; ctx.font = `${h}px ${FONT}`; ctx.textBaseline = 'alphabetic';
    lines.forEach((l, k) => ctx.fillText(l, x + 62, y + 15 + h * (k + 1) * 1.02));
  }
});

// ───────────── 렌더(빠른 카메라 이동은 서브프레임 평균으로 모션블러)
const cv = document.getElementById('c'), ctx = cv.getContext('2d');
const tmp = new OffscreenCanvas(1920, 1080), tg = tmp.getContext('2d');
const camSpeed = t => { const a = cam.at(t), b = cam.at(t + 1 / FPS); return Math.hypot(b.x - a.x, b.y - a.y) * Math.max(a.z, b.z) + Math.abs(Math.log(b.z / a.z)) * 1200; };
function render(t) {
  const v = camSpeed(t);
  if (v <= 14) { board.render(ctx, t, cam); return; }
  const n = Math.min(32, Math.max(3, Math.ceil(v * .5 / 4)));   // 서브프레임 간격 ≤ 4px(셔터 180°)
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  for (let k = 0; k < n; k++) {
    board.render(tg, t + (k / n) * (.5 / FPS), cam);   // 셔터 180°
    ctx.globalAlpha = 1 / (k + 1); ctx.drawImage(tmp, 0, 0);
  }
  ctx.globalAlpha = 1;
}

// 정지 프레임 키: 쓰는 중인 획이 없고 카메라가 멈춰 있으면 직전 프레임과 같다
const T0 = Float64Array.from(tl.strokes.map(s => s.t0));
const spans = [];                                   // 쓰는 중 구간(합친 것)
for (const s of [...tl.strokes].sort((a, b) => a.t0 - b.t0)) { const L = spans[spans.length - 1]; if (L && s.t0 <= L[1]) L[1] = Math.max(L[1], s.t1); else spans.push([s.t0, s.t1]); }
const inSpan = t => { let lo = 0, hi = spans.length - 1; while (lo <= hi) { const m = (lo + hi) >> 1; if (spans[m][1] < t) lo = m + 1; else if (spans[m][0] > t) hi = m - 1; else return true; } return false; };
const started = t => { let lo = 0, hi = T0.length; while (lo < hi) { const m = (lo + hi) >> 1; if (T0[m] < t) lo = m + 1; else hi = m; } return lo; };
const camMoving = t => { const a = cam.at(t), b = cam.at(t + 1 / FPS), c0 = cam.at(t - 1 / FPS); return a.x !== b.x || a.y !== b.y || a.z !== b.z || a.x !== c0.x || a.y !== c0.y || a.z !== c0.z; };
function sig(t) {
  if (inSpan(t) || camMoving(t)) return null;
  const c = cam.at(t);
  return `${started(t)}|${c.x.toFixed(1)},${c.y.toFixed(1)},${c.z.toFixed(4)}|${q.get('burn') === '1' ? subAt(t) : ''}`;
}

// 소리 이벤트(화면 x 로 팬, 카메라 배율로 크기)
const EV = tl.ev.map(e => { if (e.x == null) return e; const c = cam.at(e.t), [sx] = W.toScreen(c, e.x, e.y); return { ...e, sx: Math.round(sx), z: +c.z.toFixed(3) }; });

window.DUR = S.dur; window.EV = EV; window.render = render; window.sig = sig; window.CV = cv;
window.STILLS = S.slides.flatMap((sl, i) => {
  const nm = `${String(i + 1).padStart(2, '0')}_${sl.kind}`, out = [{ t: +(Math.max(sl.t0 + 1, sl.t1 - .7)).toFixed(2), name: nm }];
  if (extra.some(e => e.si === i)) out.unshift({ t: +(sl.t0 + 1.8).toFixed(2), name: nm + '_callback' });
  return out;
});
window.INFO = { cols: COLS, rows: ROWS, board: [BW, BH], strokes: tl.strokes.length, jobs: jobs.length, zooms: laid.map(r => +r.F.z.toFixed(2)) };
window.READY = true;
