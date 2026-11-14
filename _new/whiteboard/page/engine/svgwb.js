// 원고 그림(SVG)·표(HTML table)를 칠판 마커 획으로 바꾼다. 색은 뜻으로만 쓴다:
//   진한 파랑·채운 상자 → 파랑, 빨강·주황 계열 → 주황(핵심), 나머지 → 검정. 옅은 채움은 버린다(보드는 흰색).
import * as W from './wb.js';
import { htext, wrap, measure } from './hangul.js';

export const C = { ink: W.INK.black, blue: W.INK.blue, acc: W.INK.orange };

function rgb(s) {
  if (!s || s === 'none' || s === 'transparent') return null;
  s = s.trim();
  if (s[0] === '#') { if (s.length === 4) s = '#' + [...s.slice(1)].map(c => c + c).join(''); return [1, 3, 5].map(i => parseInt(s.slice(i, i + 2), 16)); }
  const m = s.match(/rgba?\(([^)]+)\)/); if (m) return m[1].split(',').slice(0, 3).map(Number);
  const named = { white: [255, 255, 255], black: [0, 0, 0], red: [220, 40, 40], blue: [40, 80, 200], gray: [128, 128, 128], grey: [128, 128, 128], orange: [230, 130, 40] };
  return named[s.toLowerCase()] || [60, 60, 60];
}
const lum = c => (0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]) / 255;
// 'light' | 'acc' | 'blue' | 'ink'
export function role(col) {
  const c = rgb(col); if (!c) return null;
  if (lum(c) > .78) return 'light';
  const [r, g, b] = c;
  if (r > g + 45 && r > b + 45) return 'acc';
  if (b > r + 30 && lum(c) < .72) return 'blue';
  return 'ink';
}
const ink = r => r === 'acc' ? C.acc : r === 'blue' ? C.blue : C.ink;
const attr = (el, k, d = null) => { const v = el.getAttribute(k) ?? el.style?.[k]; return v == null || v === '' ? d : v; };
const num = (el, k, d = 0) => { const v = parseFloat(attr(el, k)); return isNaN(v) ? d : v; };
// 상속 속성(fill 등)은 조상에서 찾는다
function inh(el, k) { for (let e = el; e && e.tagName; e = e.parentElement) { const v = e.getAttribute(k); if (v != null && v !== '') return v; if (e.tagName.toLowerCase() === 'svg') break; } return null; }

// svg 문자열 → {items:[{shapes:Stroke[]|Glyph[], kind}], w, h} (월드 좌표, 상자 (ox,oy)에서 배율 S)
export function svgToStrokes(src, box) {
  const host = document.createElement('div'); host.style.cssText = 'position:absolute;left:-99999px;top:0;visibility:hidden';
  host.innerHTML = src; document.body.appendChild(host);
  const svg = host.querySelector('svg'); if (!svg) { host.remove(); return { items: [], w: 0, h: 0 }; }
  const vb = (svg.getAttribute('viewBox') || `0 0 ${num(svg, 'width', 520)} ${num(svg, 'height', 190)}`).split(/[\s,]+/).map(Number);
  svg.setAttribute('width', vb[2]); svg.setAttribute('height', vb[3]);
  const S = Math.min(box.w / vb[2], box.h / vb[3]);
  const ox = box.x + (box.w - vb[2] * S) / 2, oy = box.y;
  const root = svg.getScreenCTM().inverse();
  const P = (el, x, y) => {                         // 요소 좌표 → 월드
    const m = root.multiply(el.getScreenCTM()); const p = new DOMPoint(x, y).matrixTransform(m);
    return [ox + (p.x - vb[0]) * S, oy + (p.y - vb[1]) * S];
  };
  const items = [];
  const lw = el => Math.max(5, Math.min(10, num(el, 'stroke-width', 1.5) * S * .9));
  const markerEnd = el => /url\(/.test(attr(el, 'marker-end') || '');
  const markerStart = el => /url\(/.test(attr(el, 'marker-start') || '');
  const head = (pts, col, w) => {                    // 화살촉: 마지막 두 점 방향
    const n = pts.length; if (n < 2) return [];
    const [ex, ey] = pts[n - 1]; let k = n - 2; while (k > 0 && Math.hypot(pts[k][0] - ex, pts[k][1] - ey) < 20) k--;
    const a = Math.atan2(ey - pts[k][1], ex - pts[k][0]), hl = Math.max(20, 9 * S);
    return [W.line(ex + Math.cos(a + 2.6) * hl, ey + Math.sin(a + 2.6) * hl, ex, ey, { color: col, w, bow: 0 }),
            W.line(ex, ey, ex + Math.cos(a - 2.6) * hl, ey + Math.sin(a - 2.6) * hl, { color: col, w, bow: 0 })];
  };
  const outline = (el, closed) => {                  // 채움·선 색 → 획 색·굵기·빗금 여부
    const f = role(inh(el, 'fill') ?? 'black'), s = role(inh(el, 'stroke'));
    if (f && f !== 'light') return { col: ink(f), w: lw(el) + 1, hatch: closed };
    if (s && s !== 'light') return { col: ink(s), w: lw(el), hatch: false };
    if (closed && (f === 'light' || s === 'light')) return { col: C.blue, w: 5, hatch: false, faint: true };
    return null;
  };
  for (const el of svg.querySelectorAll('rect,line,circle,ellipse,path,polyline,polygon,text')) {
    if (el.closest('defs,marker,clipPath,mask,pattern,symbol')) continue;
    const tag = el.tagName.toLowerCase();
    try {
      if (tag === 'text') {
        const parts = el.querySelectorAll('tspan').length ? [...el.querySelectorAll('tspan')] : [el];
        for (const t of parts) {
          const str = t.textContent.trim(); if (!str) continue;
          const fs = parseFloat(inh(t, 'font-size')) || 12, anchor = inh(t, 'text-anchor') || 'start';
          const x = t.hasAttribute('x') ? num(t, 'x') : num(el, 'x'), y = t.hasAttribute('y') ? num(t, 'y') : num(el, 'y');
          const [wx, wy] = P(t === el ? el : el, x, y);
          let r = role(inh(t, 'fill') || 'black'); if (r === 'light' || r === null) r = 'ink';
          const h = Math.max(34, fs * S * 1.6);
          const m = root.multiply(el.getScreenCTM()), rot = Math.atan2(m.b, m.a);
          const bold = /bold|[6-9]00/.test(inh(t, 'font-weight') || '');
          items.push({ kind: 'text', shapes: htext(str, wx, wy, { h, color: ink(r), align: anchor === 'middle' ? 'center' : anchor === 'end' ? 'right' : 'left', rot, bold }) });
        }
        continue;
      }
      if (tag === 'rect') {
        const x = num(el, 'x'), y = num(el, 'y'), w = num(el, 'width'), h = num(el, 'height'), rx = num(el, 'rx', num(el, 'ry'));
        if (w * S < 4 || h * S < 4) continue;
        const o = outline(el, true); if (!o) continue;
        const [a, b] = P(el, x, y), [c, d] = P(el, x + w, y + h);
        const X = Math.min(a, c), Y = Math.min(b, d), Wd = Math.abs(c - a), Hd = Math.abs(d - b);
        const sh = rx * S > 6 ? [W.roundRect(X, Y, Wd, Hd, Math.min(rx * S, Hd / 2, 40), { color: o.col, w: o.w, alpha: o.faint ? .55 : .94 })] : W.rect(X, Y, Wd, Hd, { color: o.col, w: o.w, over: 5, alpha: o.faint ? .55 : .94 });
        if (o.hatch && Wd > 30 && Hd > 20) sh.push(W.hatch([[X + 6, Y + 6], [X + Wd - 6, Y + 6], [X + Wd - 6, Y + Hd - 6], [X + 6, Y + Hd - 6]], { color: o.col, alpha: .14, w: 7, spacing: 22 }));
        items.push({ kind: 'shape', shapes: sh });
        continue;
      }
      if (tag === 'line') {
        const s = role(inh(el, 'stroke')) || 'ink'; if (s === 'light') continue;
        const p0 = P(el, num(el, 'x1'), num(el, 'y1')), p1 = P(el, num(el, 'x2'), num(el, 'y2'));
        const col = ink(s), w = lw(el), dash = attr(el, 'stroke-dasharray');
        const sh = dash && dash !== 'none' ? W.dashed([p0, p1], { color: col, w, dash: 26, gap: 18 }) : [W.line(...p0, ...p1, { color: col, w })];
        if (markerEnd(el)) sh.push(...head([p0, p1], col, w));
        if (markerStart(el)) sh.push(...head([p1, p0], col, w));
        items.push({ kind: 'shape', shapes: sh });
        continue;
      }
      if (tag === 'circle' || tag === 'ellipse') {
        const cx = num(el, 'cx'), cy = num(el, 'cy'), rx = tag === 'circle' ? num(el, 'r') : num(el, 'rx'), ry = tag === 'circle' ? rx : num(el, 'ry');
        const o = outline(el, true); if (!o) continue;
        const [X, Y] = P(el, cx, cy), R = rx * S, RY = ry * S;
        if (R < 7) { items.push({ kind: 'dot', shapes: [W.poly([X, Y, X + 1, Y + 1], { color: o.col, w: Math.max(8, R * 2) })] }); continue; }
        const sh = [W.circle(X, Y, R, { ry: RY, color: o.col, w: o.w, alpha: o.faint ? .55 : .94 })];
        items.push({ kind: 'shape', shapes: sh });
        continue;
      }
      // path / polyline / polygon → 점 열(서브패스마다 나눔)
      let runs = [];
      if (tag === 'path') {
        const L = el.getTotalLength(); if (!(L > 0)) continue;
        const n = Math.max(2, Math.min(400, Math.ceil(L * S / 7))); let cur = [], prev = null;
        for (let i = 0; i <= n; i++) {
          const q = el.getPointAtLength(L * i / n), w = P(el, q.x, q.y);
          if (prev && Math.hypot(w[0] - prev[0], w[1] - prev[1]) > Math.max(30, 4 * L * S / n)) { if (cur.length > 1) runs.push(cur); cur = []; }
          cur.push(w); prev = w;
        }
        if (cur.length > 1) runs.push(cur);
      } else {
        const v = (attr(el, 'points') || '').trim().split(/[\s,]+/).map(Number), pts = [];
        for (let i = 0; i + 1 < v.length; i += 2) pts.push(P(el, v[i], v[i + 1]));
        if (tag === 'polygon' && pts.length) pts.push(pts[0]);
        if (pts.length > 1) runs.push(pts);
      }
      const closed = tag === 'polygon' || /z\s*$/i.test(attr(el, 'd') || '');
      const o = outline(el, closed); if (!o || !runs.length) continue;
      const sh = [];
      for (const r of runs) {
        const ext = Math.max(...r.map(p => p[0])) - Math.min(...r.map(p => p[0])) + Math.max(...r.map(p => p[1])) - Math.min(...r.map(p => p[1]));
        if (ext < 14) { sh.push(W.poly([r[0][0], r[0][1], r[0][0] + 1, r[0][1] + 1], { color: o.col, w: 9 })); continue; }   // 작은 화살촉 모양 등은 점으로
        sh.push(W.poly(r.flat(), { color: o.col, w: o.w, smooth: 1, alpha: o.faint ? .55 : .94 }));
      }
      if (markerEnd(el) && runs.length) sh.push(...head(runs[runs.length - 1], o.col, o.w));
      items.push({ kind: 'shape', shapes: sh });
    } catch (e) { console.warn('svg element skipped', tag, e.message); }
  }
  host.remove();
  return { items, w: vb[2] * S, h: vb[3] * S, x: ox, y: oy };
}

// <table> → 손으로 그은 격자 + 셀 글씨. 열 너비는 글자 수에 비례, 셀 안에서 줄바꿈.
export function tableToStrokes(src, box) {
  const host = document.createElement('div'); host.innerHTML = src;
  const rows = [...host.querySelectorAll('tr')].map(tr => [...tr.querySelectorAll('th,td')].map(c => ({ text: c.textContent.replace(/\s+/g, ' ').trim(), th: c.tagName === 'TH' })));
  if (!rows.length) return { items: [], w: 0, h: 0 };
  const nc = Math.max(...rows.map(r => r.length));
  let h = 40;
  const pad = 16;
  for (let tries = 0; tries < 12; tries++) {
    const want = [...Array(nc)].map((_, j) => Math.max(...rows.map(r => r[j] ? measure(r[j].text, h) : 0)) + pad * 2);
    const tot = want.reduce((a, b) => a + b, 0), k = Math.min(1, box.w / tot);
    const cw = want.map(v => Math.max(h * 2.4, v * k)), cs = cw.reduce((a, b) => a + b, 0), cwn = cw.map(v => v * Math.min(1, box.w / cs));
    const lines = rows.map(r => r.map((c, j) => wrap(c.text, h, cwn[j] - pad * 2)));
    const rh = lines.map(r => Math.max(...r.map(l => l.length)) * h * 1.2 + pad * 1.4);
    const H = rh.reduce((a, b) => a + b, 0);
    if (H <= box.h || h <= 26) { return layoutTable(rows, lines, cwn, rh, h, pad, box); }
    h -= 2;
  }
}
function layoutTable(rows, lines, cw, rh, h, pad, box) {
  const Wd = cw.reduce((a, b) => a + b, 0), Hd = rh.reduce((a, b) => a + b, 0), x0 = box.x + (box.w - Wd) / 2, y0 = box.y;
  const items = [];
  const grid = [...W.rect(x0, y0, Wd, Hd, { color: C.ink, w: 7, over: 6 })];
  let y = y0; for (let i = 0; i < rh.length - 1; i++) { y += rh[i]; grid.push(W.line(x0 - 4, y, x0 + Wd + 4, y, { color: C.ink, w: i === 0 ? 7 : 5 })); }
  let x = x0; for (let j = 0; j < cw.length - 1; j++) { x += cw[j]; grid.push(W.line(x, y0 - 4, x, y0 + Hd + 4, { color: C.ink, w: 5 })); }
  items.push({ kind: 'shape', shapes: grid });
  y = y0;
  rows.forEach((r, i) => {
    let xx = x0;
    r.forEach((c, j) => {
      const ls = lines[i][j];
      const sh = []; ls.forEach((ln, k) => sh.push(...htext(ln, xx + pad, y + pad * .7 + h * .82 + k * h * 1.2, { h, color: c.th ? C.blue : C.ink, bold: c.th })));
      if (sh.length) items.push({ kind: 'text', shapes: sh, row: i });
      xx += cw[j];
    });
    y += rh[i];
  });
  return { items, w: Wd, h: Hd, x: x0, y: y0 };
}
