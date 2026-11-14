// 한글 손글씨 — 단선(single-line) 한글 폰트가 없으므로, 글자마다 손글씨 폰트(Nanum Pen Script) 외곽선을
// 쓰는 방향(왼→오, 살짝 비스듬히)으로 쓸어 가며 드러낸다. 글자 하나 = wb.js 의 획 하나(같은 Timeline·소리 이벤트).
//   htext(str, x, y, {h, color, align, maxW, lead, bold}) → Glyph[] (+ .width .height .lines)
//   wb.js Board.render 는 s.paint 가 있으면 ribbon 대신 paint(ig, prog) 를 부른다([local] 패치).
import { mulberry, TAU, clamp } from './lib.js';

export const FONT = 'NP';                           // index.html 의 @font-face 이름
const M = new OffscreenCanvas(8, 8).getContext('2d');
let SEED = 91;

export function measure(str, h) { M.font = `${h}px ${FONT}`; return M.measureText(str).width; }

// 줄 나누기: 공백 단위로, 안 되면 글자 단위로
export function wrap(str, h, maxW) {
  if (!maxW || measure(str, h) <= maxW) return [str];
  const out = []; let cur = '';
  const push = w => { if (cur && measure(cur + w, h) > maxW) { out.push(cur.trimEnd()); cur = ''; } cur += w; };
  for (const word of str.split(/(?<=\s)/)) {
    if (measure(word, h) > maxW) { for (const ch of word) push(ch); } else push(word);
  }
  if (cur.trim()) out.push(cur.trimEnd());
  return out;
}

class Glyph {
  constructor(ch, cx, y, adv, h, o, R) {
    this.ch = ch; this.cx = cx; this.y = y; this.adv = adv; this.h = h;
    this.color = o.color || null; this.alpha = o.alpha ?? .94; this.kind = 'text'; this.bold = o.bold ? 1 : 0;
    this.rot = (o.rot ?? 0) + (R() - .5) * .06; this.dy = (R() - .5) * h * .05; this.sc = 1 + (R() - .5) * .06;
    this.len = Math.max(14, adv * 2.4);              // 쓰는 경로 길이(획 속도 계산용)
    this.w = Math.max(4, h * .07);
    const top = y - h * .78, bot = y + h * .22;
    this.box = [cx - adv / 2 - h * .2, top - h * .2, cx + adv / 2 + h * .2, bot + h * .2];
    this.t0 = 1e9; this.t1 = 1e9;
  }
  get start() { return [this.cx - this.adv / 2, this.y - this.h * .35]; }
  get end() { return [this.cx + this.adv / 2, this.y - this.h * .25]; }
  at(L) { const u = clamp(L / this.len); const a = this.start, b = this.end; return [a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u]; }
  prog(t) { if (t <= this.t0) return 0; if (t >= this.t1) return 1; const u = (t - this.t0) / (this.t1 - this.t0); return u - Math.sin(TAU * u) / TAU * .8; }
  paint(g, p) {
    if (p <= 0) return;
    const h = this.h, a = this.adv;
    g.translate(this.cx, this.y + this.dy); g.rotate(this.rot); g.scale(this.sc, this.sc);
    if (p < 1) {                                     // 비스듬한 쓸기 마스크(위가 조금 앞선다)
      const k = h * .35, xe = -a / 2 - k + p * (a + 2 * k);
      g.beginPath(); g.moveTo(-a, -h * 1.2); g.lineTo(xe + k, -h * 1.2); g.lineTo(xe - k, h * .5); g.lineTo(-a, h * .5); g.closePath(); g.clip();
    }
    g.globalAlpha = this.alpha; g.fillStyle = g.strokeStyle = this.color || '#23262c';
    g.font = `${h}px ${FONT}`; g.textAlign = 'center'; g.textBaseline = 'alphabetic';
    g.lineJoin = 'round'; g.lineWidth = h * (.022 + this.bold * .02);   // 마커 굵기
    g.fillText(this.ch, 0, 0); g.strokeText(this.ch, 0, 0);
  }
}

// 여러 줄 손글씨. y 는 첫 줄 기준선. 반환 배열에 .width(가장 긴 줄) .height(전체 높이) .lines
export function htext(str, x, y, o = {}) {
  const h = o.h ?? 60, lead = o.lead ?? 1.28, R = mulberry(o.seed ?? (SEED += 17));
  const lines = o.maxW ? wrap(String(str), h, o.maxW) : [String(str)];
  const out = []; let W = 0;
  lines.forEach((ln, li) => {
    M.font = `${h}px ${FONT}`;
    const lw = M.measureText(ln).width; W = Math.max(W, lw);
    const x0 = o.align === 'center' ? x - lw / 2 : o.align === 'right' ? x - lw : x, yy = y + li * h * lead;
    let acc = '';
    for (const ch of ln) {
      const a0 = M.measureText(acc).width; acc += ch; const a1 = M.measureText(acc).width;
      if (ch.trim()) out.push(new Glyph(ch, x0 + (a0 + a1) / 2, yy, a1 - a0, h, o, R));
    }
  });
  out.width = W; out.height = h * (1 + (lines.length - 1) * lead); out.lines = lines.length;
  return out;
}
