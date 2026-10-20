import { uuid } from '../lib/uuid';
import { getStroke } from 'perfect-freehand';
import type { InkPoint, Stroke } from '@hsb/shared';

export type Tool = 'view' | 'pen' | 'highlighter' | 'eraser';

export const PEN_COLORS = ['#111827', '#1d4ed8', '#dc2626', '#059669'];
export const HIGHLIGHT_COLORS = ['#facc15', '#4ade80', '#60a5fa', '#f472b6'];
/** 기준 폭 = 페이지 너비 비율 */
export const PEN_SIZES = [0.002, 0.0035, 0.006];
export const HIGHLIGHT_SIZE = 0.02;

/** 모든 점의 필압이 같으면(마우스·필압 없는 펜) 속도로 필압을 흉내 낸다 */
function hasPressure(points: InkPoint[]): boolean {
  return points.some((p) => Math.abs(p[2] - points[0][2]) > 0.01);
}

function outline(s: Stroke, w: number, h: number, last: boolean): Path2D {
  const pts = s.points.map(([x, y, p]) => [x * w, y * h, p]);
  const hl = s.tool === 'highlighter';
  const poly = getStroke(pts, {
    size: s.size * w * (hl ? 1 : 2.2),
    thinning: hl ? 0 : 0.6,
    smoothing: 0.5,
    streamline: hl ? 0.6 : 0.4,
    simulatePressure: !hl && !hasPressure(s.points),
    last,
    start: { cap: !hl, taper: 0 },
    end: { cap: !hl, taper: 0 },
  });
  const path = new Path2D();
  if (!poly.length) return path;
  path.moveTo(poly[0][0], poly[0][1]);
  for (let i = 1; i < poly.length; i++) {
    const [x0, y0] = poly[i];
    const [x1, y1] = poly[(i + 1) % poly.length];
    path.quadraticCurveTo(x0, y0, (x0 + x1) / 2, (y0 + y1) / 2);
  }
  path.closePath();
  return path;
}

/** 형광펜을 먼저, 펜을 나중에 그려 글씨가 형광펜 위에 오게 한다 */
export function drawStrokes(ctx: CanvasRenderingContext2D, strokes: readonly Stroke[], w: number, h: number, live = false) {
  for (const pass of ['highlighter', 'pen'] as const) {
    for (const s of strokes) {
      if (s.tool !== pass) continue;
      ctx.globalAlpha = pass === 'highlighter' ? 0.35 : 1;
      ctx.globalCompositeOperation = pass === 'highlighter' ? 'multiply' : 'source-over';
      ctx.fillStyle = s.color;
      ctx.fill(outline(s, w, h, !live));
    }
  }
  ctx.globalAlpha = 1;
  ctx.globalCompositeOperation = 'source-over';
}

/** (x,y) 정규화 좌표 근처(반경 r, 페이지 너비 비율)를 지나는 획 */
export function hitStrokes(strokes: readonly Stroke[], x: number, y: number, r: number, aspect: number): Stroke[] {
  const r2 = r * r;
  return strokes.filter((s) => {
    const rr = r2 + (s.size * 1.2) ** 2;
    return s.points.some(([px, py]) => {
      const dx = px - x;
      const dy = (py - y) * aspect; // 세로 좌표를 너비 기준으로 환산
      return dx * dx + dy * dy <= rr;
    });
  });
}

export function newStrokeId(): string {
  return uuid();
}
