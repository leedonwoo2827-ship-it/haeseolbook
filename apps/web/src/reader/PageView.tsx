import { memo, useEffect, useLayoutEffect, useRef, useState } from 'react';
import type { Page, Region, Stroke, VideoCue } from '@hsb/shared';
import { drawStrokes, hitStrokes, newStrokeId, type Tool } from './ink';

/** 문항별 채점 결과(가장 최근) — 원문 위 보기에 ○·✕ 를 그린다 */
export interface ChoiceResult { chosen: number; answer: number }

/** 탭 판정: 누른 뒤 이만큼(0–1 좌표) 안 움직이고 이 시간 안에 떼면 탭 */
const TAP_MOVE = 0.012;
const TAP_MS = 900;   // 펜을 꾹 누르다 떼도 탭으로(제자리에 찍은 점은 필기가 아니다)
/** 원숫자 위에 그린 작은 ✓·○ — 획의 가운데가 보기 칸 왼쪽 이 폭(0–1) 안, 획 크기가 이 이하 */
const MARK_ZONE = 0.05;
const MARK_MAX = 0.06;
/** 원숫자 바로 왼쪽·위아래에 찍혀도 그 보기로 — 보기 칸은 원숫자 왼쪽 끝에서 시작한다 */
const CHOICE_PAD_X = 0.025;
const CHOICE_PAD_Y = 0.004;

const inBox = (r: Region, x: number, y: number) =>
  x >= r.bbox.x && x <= r.bbox.x + r.bbox.w && y >= r.bbox.y && y <= r.bbox.y + r.bbox.h;

export interface PageViewProps {
  page: Page;
  urls: { xs: string; sm: string; hi: string };
  regions: Region[];
  strokes: Stroke[];
  tool: Tool;
  color: string;
  size: number;
  /** 손가락으로도 그릴지. 펜이 한 번 감지되면 자동으로 끈다(팜 리젝션) */
  fingerDraw: boolean;
  activeQuizId: string | null;
  /** 이용자 식별 워터마크 (이미지 유출 추적용) */
  watermark: string;
  cue: VideoCue | null;
  videoTime: () => number | null;
  onPenDetected: () => void;
  onChange: (pageId: string, strokes: Stroke[], removedIds: string[]) => void;
  onRegionTap: (quizId: string) => void;
  /** 원문의 보기 칸(①②③④)을 펜·손가락·마우스로 한 번 누르면 — 정답펜 같은 모드 없이 그대로 채점 */
  onChoiceTap: (quizId: string, choiceNo: number) => void;
  results: Map<string, ChoiceResult>;
  onStrokeTap: (stroke: Stroke) => void;
  /** 손가락 드래그로 직접 스크롤할 컨테이너 (그리기 모드에서) */
  scroller: React.RefObject<HTMLElement>;
}

function PageViewImpl(p: PageViewProps) {
  const wrap = useRef<HTMLDivElement>(null);
  const base = useRef<HTMLCanvasElement>(null);
  const live = useRef<HTMLCanvasElement>(null);
  const [width, setWidth] = useState(0);
  const [visible, setVisible] = useState(false);
  const drawing = useRef<{ id: number; stroke: Stroke | null; erased: Set<string>; panY?: number; panX?: number; x0: number; y0: number; t0: number } | null>(null);
  /** 탭으로 채점했으면 뒤따르는 click(보기 모드 처리)을 한 번 건너뛴다 */
  const tapped = useRef(false);
  const choices = p.regions.filter((r) => r.kind === 'choice' && r.quizId && r.choiceNo);
  const choiceAt = (x: number, y: number) =>
    choices.find((r) => inBox(r, x, y)) ??
    choices.find((r) => x >= r.bbox.x - CHOICE_PAD_X && x <= r.bbox.x + r.bbox.w && y >= r.bbox.y - CHOICE_PAD_Y && y <= r.bbox.y + r.bbox.h + CHOICE_PAD_Y);
  const aspect = p.page.height / p.page.width;

  useLayoutEffect(() => {
    const el = wrap.current!;
    const ro = new ResizeObserver(() => setWidth(el.clientWidth));
    ro.observe(el);
    const io = new IntersectionObserver(([e]) => e.isIntersecting && setVisible(true), { rootMargin: '1200px 0px' });
    io.observe(el);
    return () => { ro.disconnect(); io.disconnect(); };
  }, []);

  const dpr = Math.min(window.devicePixelRatio || 1, 3);
  const pxW = Math.min(4096, Math.round(width * dpr));
  const pxH = Math.round(pxW * aspect);
  // 화면 폭 × DPR 에 맞는 해상도만 받는다
  const src = width * dpr > 1300 ? p.urls.hi : width * dpr > 400 ? p.urls.sm : p.urls.xs;

  useEffect(() => {
    const c = base.current;
    if (!c || !pxW) return;
    c.width = pxW;
    c.height = pxH;
    const ctx = c.getContext('2d')!;
    ctx.clearRect(0, 0, pxW, pxH);
    const erased = drawing.current?.erased;
    drawStrokes(ctx, erased?.size ? p.strokes.filter((s) => !erased.has(s.id)) : p.strokes, pxW, pxH);
    if (live.current) { live.current.width = pxW; live.current.height = pxH; }
  }, [p.strokes, pxW, pxH]);

  const norm = (e: { clientX: number; clientY: number }) => {
    const r = live.current!.getBoundingClientRect();
    return [Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)), Math.min(1, Math.max(0, (e.clientY - r.top) / r.height))] as const;
  };

  const redrawBaseWithout = (erased: Set<string>) => {
    const ctx = base.current!.getContext('2d')!;
    ctx.clearRect(0, 0, pxW, pxH);
    drawStrokes(ctx, p.strokes.filter((s) => !erased.has(s.id)), pxW, pxH);
  };

  const eraseAt = (x: number, y: number) => {
    const d = drawing.current!;
    const hit = hitStrokes(p.strokes.filter((s) => !d.erased.has(s.id)), x, y, 0.012, aspect);
    if (hit.length) {
      hit.forEach((s) => d.erased.add(s.id));
      redrawBaseWithout(d.erased);
    }
  };

  const onPointerDown = (e: React.PointerEvent) => {
    if (p.tool === 'view' || drawing.current) return;
    if (e.pointerType === 'pen') p.onPenDetected();
    const fingerPan = e.pointerType === 'touch' && !p.fingerDraw;
    if (e.pointerType === 'mouse' && e.button !== 0) return;
    e.currentTarget.setPointerCapture(e.pointerId);
    const [x, y] = norm(e);
    const t0 = performance.now();
    if (fingerPan) {
      drawing.current = { id: e.pointerId, stroke: null, erased: new Set(), panY: e.clientY, panX: e.clientX, x0: x, y0: y, t0 };
      return;
    }
    drawing.current = { id: e.pointerId, stroke: null, erased: new Set(), x0: x, y0: y, t0 };
    if (p.tool === 'eraser') return eraseAt(x, y);
    const vt = p.videoTime();
    drawing.current.stroke = {
      id: newStrokeId(), tool: p.tool, color: p.color, size: p.size,
      points: [[x, y, e.pressure || 0.5]], videoTime: vt === null ? null : Math.round(vt * 10) / 10, createdAt: Date.now(),
    };
  };

  const onPointerMove = (e: React.PointerEvent) => {
    const d = drawing.current;
    if (!d || d.id !== e.pointerId) return;
    if (d.panY !== undefined) {
      p.scroller.current?.scrollBy({ top: d.panY - e.clientY, left: (d.panX ?? e.clientX) - e.clientX });
      d.panY = e.clientY;
      d.panX = e.clientX;
      return;
    }
    const events = (e.nativeEvent as PointerEvent).getCoalescedEvents?.() ?? [e.nativeEvent];
    if (p.tool === 'eraser') {
      for (const ev of events) eraseAt(...norm(ev));
      return;
    }
    if (!d.stroke) return;
    for (const ev of events) {
      const [x, y] = norm(ev);
      const last = d.stroke.points[d.stroke.points.length - 1];
      if (Math.abs(last[0] - x) + Math.abs(last[1] - y) < 0.0008) continue;
      if (d.stroke.points.length < 4999) d.stroke.points.push([round(x), round(y), round(ev.pressure || 0.5)]);
    }
    const ctx = live.current!.getContext('2d')!;
    ctx.clearRect(0, 0, pxW, pxH);
    drawStrokes(ctx, [d.stroke], pxW, pxH, true);
  };

  const onPointerUp = (e: React.PointerEvent) => {
    const d = drawing.current;
    if (!d || d.id !== e.pointerId) return;
    drawing.current = null;
    live.current?.getContext('2d')?.clearRect(0, 0, pxW, pxH);
    if (p.tool !== 'eraser' && p.tool !== 'highlighter' && e.type === 'pointerup') {
      const [x, y] = norm(e);
      const pts = d.stroke?.points ?? [[d.x0, d.y0], [x, y]];
      const xs = pts.map((q) => q[0]), ys = pts.map((q) => q[1]);
      const w = Math.max(...xs) - Math.min(...xs), h = Math.max(...ys) - Math.min(...ys);
      if (w <= TAP_MOVE && h <= TAP_MOVE && performance.now() - d.t0 <= TAP_MS) {
        // 탭: 원숫자를 콕 — 채점만 하고 점은 필기로 남기지 않는다
        const c = choiceAt(d.x0, d.y0);
        if (c) { tapped.current = true; p.onChoiceTap(c.quizId!, c.choiceNo!); return; }
      } else if (d.stroke && w <= MARK_MAX && h <= MARK_MAX * 1.6) {
        // 원숫자 위에 작게 ✓·○ — 채점하고 필기로도 남긴다
        const cx = (Math.max(...xs) + Math.min(...xs)) / 2, cy = (Math.max(...ys) + Math.min(...ys)) / 2;
        const c = choiceAt(cx, cy);
        if (c && cx >= c.bbox.x - CHOICE_PAD_X && cx <= c.bbox.x + MARK_ZONE) p.onChoiceTap(c.quizId!, c.choiceNo!);
      }
    }
    if (d.stroke) p.onChange(p.page.id, [...p.strokes, d.stroke], []);
    else if (d.erased.size) p.onChange(p.page.id, p.strokes.filter((s) => !d.erased.has(s.id)), [...d.erased]);
  };

  /** 보기 모드에서 탭: 필기 → 그 시점 영상으로, 문항 영역 → 해당 해설 구간으로 */
  const onClick = (e: React.MouseEvent) => {
    if (tapped.current) { tapped.current = false; return; }
    if (p.tool !== 'view') return;
    const [x, y] = norm(e);
    const choice = choiceAt(x, y);
    if (choice) return p.onChoiceTap(choice.quizId!, choice.choiceNo!);
    const hit = hitStrokes(p.strokes.filter((s) => s.videoTime !== null), x, y, 0.015, aspect).pop();
    if (hit) return p.onStrokeTap(hit);
    const region = p.regions.find((r) => r.quizId && r.kind === 'quiz' && inBox(r, x, y));
    if (region?.quizId) p.onRegionTap(region.quizId);
  };

  return (
    <div ref={wrap} className="page" style={{ aspectRatio: `${p.page.width} / ${p.page.height}` }} data-page-id={p.page.id}>
      {visible && <img src={src} alt={`${p.page.pageNo}쪽`} draggable={false} />}
      <svg className="page-overlay" viewBox="0 0 1000 1000" preserveAspectRatio="none" aria-hidden>
        {p.regions.filter((r) => r.quizId && r.kind === 'quiz').map((r) => (
          <rect key={r.id} x={r.bbox.x * 1000} y={r.bbox.y * 1000} width={r.bbox.w * 1000} height={r.bbox.h * 1000}
            className={r.quizId === p.activeQuizId ? 'region active' : 'region'} rx="4" vectorEffect="non-scaling-stroke" />
        ))}
        {/* 보기 칸 — 보이지 않는 자리표(테스트·접근성용). 누르기 판정은 캔버스가 좌표로 한다 */}
        {choices.map((r) => (
          <rect key={r.id} x={r.bbox.x * 1000} y={r.bbox.y * 1000} width={r.bbox.w * 1000} height={r.bbox.h * 1000}
            className="choice-box" data-quiz={r.quizId!} data-choice={r.choiceNo!} />
        ))}
      </svg>
      {choices.map((r) => {
        const res = p.results.get(r.quizId!);
        const mark = !res ? null : r.choiceNo === res.answer ? 'ok' : r.choiceNo === res.chosen ? 'bad' : null;
        return mark && (
          <span key={`${r.id}-${res!.chosen}`} className={`choice-mark ${mark}`} aria-hidden
            style={{ left: `${r.bbox.x * 100}%`, top: `${r.bbox.y * 100}%` }}>{mark === 'bad' ? '✕' : ''}</span>
        );
      })}
      {p.watermark && <div className="watermark" aria-hidden>{Array.from({ length: 6 }, (_, i) => <span key={i}>{p.watermark}</span>)}</div>}
      {p.cue && <div className="cue-dot" style={{ left: `${p.cue.x * 100}%`, top: `${p.cue.y * 100}%` }} />}
      <canvas ref={base} className="ink" />
      <canvas
        ref={live}
        className={`ink live tool-${p.tool}`}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
        onClick={onClick}
      />
      <span className="page-no">{p.page.pageNo}</span>
    </div>
  );
}

const round = (n: number) => Math.round(n * 10000) / 10000;

export const PageView = memo(PageViewImpl);
