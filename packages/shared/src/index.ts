/**
 * 해설북 공유 도메인 스키마.
 * 페이지/영역/문항/해설은 Solve의 regions(quiz|solution) 구조를 참고했고,
 * 문항별 유튜브 해설 구간(VideoSegment)과 필기의 videoTime을 더했다.
 * 좌표는 모두 페이지 기준 0–1 정규화 값이라 기기 해상도와 무관하다.
 */
import { z } from 'zod';

export const DeviceType = z.enum(['pc', 'tablet', 'phone']);
export type DeviceType = z.infer<typeof DeviceType>;

export const BBox = z.object({
  x: z.number().min(0).max(1),
  y: z.number().min(0).max(1),
  w: z.number().min(0).max(1),
  h: z.number().min(0).max(1),
});
export type BBox = z.infer<typeof BBox>;

export const ImageSize = z.enum(['xs', 'sm', 'hi']);
export type ImageSize = z.infer<typeof ImageSize>;

export const Page = z.object({
  id: z.string(),
  pageNo: z.number().int().positive(),
  width: z.number().positive(),
  height: z.number().positive(),
});
export type Page = z.infer<typeof Page>;

export const Region = z.object({
  id: z.string(),
  pageId: z.string(),
  kind: z.enum(['quiz', 'solution']),
  quizId: z.string().nullable(),
  bbox: BBox,
});
export type Region = z.infer<typeof Region>;

export const Quiz = z.object({
  id: z.string(),
  no: z.number().int().positive(),
  answer: z.number().int().positive(),
  choiceCount: z.number().int().min(2).max(5),
  keywords: z.array(z.string()).default([]),
});
export type Quiz = z.infer<typeof Quiz>;

export const Solution = z.object({
  quizId: z.string(),
  markdown: z.string(),
});
export type Solution = z.infer<typeof Solution>;

/** 해설영상 포인터 트랙의 한 점: 영상 t초에 원문 page 의 (x,y)를 가리킨다 */
export const VideoCue = z.object({
  t: z.number().min(0),
  pageNo: z.number().int().positive(),
  x: z.number().min(0).max(1),
  y: z.number().min(0).max(1),
});
export type VideoCue = z.infer<typeof VideoCue>;

export const VideoSegment = z.object({
  quizId: z.string(),
  youtubeId: z.string().regex(/^[\w-]{11}$/),
  startSec: z.number().min(0),
  endSec: z.number().min(0),
  cues: z.array(VideoCue).default([]),
}).refine((s) => s.endSec > s.startSec, { message: 'endSec must be greater than startSec' });
export type VideoSegment = z.infer<typeof VideoSegment>;

export const BookSummary = z.object({
  id: z.string(),
  title: z.string(),
  exam: z.string(),
  subject: z.string(),
  year: z.number().int(),
  round: z.string(),
  pageCount: z.number().int(),
  quizCount: z.number().int(),
  priceKrw: z.number().int().min(0),
  coverPageId: z.string().nullable(),
  owned: z.boolean().optional(),
});
export type BookSummary = z.infer<typeof BookSummary>;

/** 리더가 한 번에 받는 패키지 매니페스트 (페이지 이미지는 서명 URL로 별도 발급) */
export const BookManifest = z.object({
  book: BookSummary,
  pages: z.array(Page),
  regions: z.array(Region),
  quizzes: z.array(Quiz),
  solutions: z.array(Solution),
  videoSegments: z.array(VideoSegment),
  imageUrls: z.record(z.string(), z.object({ xs: z.string(), sm: z.string(), hi: z.string() })),
  urlExpiresAt: z.string(),
});
export type BookManifest = z.infer<typeof BookManifest>;

// ---------- 필기(ink) ----------

export const InkTool = z.enum(['pen', 'highlighter']);
export type InkTool = z.infer<typeof InkTool>;

/** [x, y, pressure] — x,y는 0–1 페이지 좌표, pressure는 0–1 */
export const InkPoint = z.tuple([z.number(), z.number(), z.number()]);
export type InkPoint = z.infer<typeof InkPoint>;

export const Stroke = z.object({
  id: z.string().min(1).max(64),
  tool: InkTool,
  color: z.string().regex(/^#[0-9a-fA-F]{6}$/),
  /** 기준 폭: 페이지 너비 대비 비율 (예: 0.003) */
  size: z.number().positive().max(0.1),
  points: z.array(InkPoint).min(1).max(5000),
  /** 필기 당시 해설영상 재생 위치(초). 영상이 없었으면 null */
  videoTime: z.number().min(0).nullable(),
  createdAt: z.number().int(),
});
export type Stroke = z.infer<typeof Stroke>;

export const INK_FORMAT_VERSION = 1;

export const InkPage = z.object({
  version: z.literal(INK_FORMAT_VERSION),
  pageId: z.string(),
  strokes: z.array(Stroke).max(5000),
});
export type InkPage = z.infer<typeof InkPage>;

/** 클라이언트 → 서버 업로드. baseRev는 클라이언트가 마지막으로 본 서버 리비전 */
export const InkPushRequest = z.object({
  bookId: z.string(),
  pageId: z.string(),
  baseRev: z.number().int().min(0),
  ink: InkPage,
  checksum: z.string(),
  deviceId: z.string(),
});
export type InkPushRequest = z.infer<typeof InkPushRequest>;

export const InkPushResponse = z.discriminatedUnion('status', [
  z.object({ status: z.literal('ok'), rev: z.number().int(), checksum: z.string() }),
  z.object({
    status: z.literal('conflict'),
    server: z.object({ rev: z.number().int(), ink: InkPage, checksum: z.string() }),
  }),
]);
export type InkPushResponse = z.infer<typeof InkPushResponse>;

export const QuizAttemptRequest = z.object({
  quizId: z.string(),
  chosen: z.number().int().positive(),
});
export type QuizAttemptRequest = z.infer<typeof QuizAttemptRequest>;

// ---------- 순수 함수 (웹/서버 공용) ----------

/** 재생 시각에 해당하는 해설 구간. 구간이 겹치면 가장 늦게 시작한 것을 고른다. */
export function segmentAt(segments: readonly VideoSegment[], t: number): VideoSegment | null {
  let best: VideoSegment | null = null;
  for (const s of segments) {
    if (t >= s.startSec && t < s.endSec && (!best || s.startSec > best.startSec)) best = s;
  }
  return best;
}

/** 포인터 트랙에서 t초의 위치를 선형 보간. 트랙 범위 밖이거나 페이지가 바뀌는 구간이면 가장 가까운 앞 점 */
export function cueAt(cues: readonly VideoCue[], t: number): VideoCue | null {
  if (!cues.length || t < cues[0].t) return null;
  let lo = 0;
  let hi = cues.length - 1;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if (cues[mid].t <= t) lo = mid; else hi = mid - 1;
  }
  const a = cues[lo];
  const b = cues[lo + 1];
  if (!b || b.pageNo !== a.pageNo || b.t === a.t) return a;
  const k = (t - a.t) / (b.t - a.t);
  return { t, pageNo: a.pageNo, x: a.x + (b.x - a.x) * k, y: a.y + (b.y - a.y) * k };
}

/** 결정적 체크섬(FNV-1a 32bit ×2). 브라우저·Node 동기 실행용이며 보안 목적이 아니다. */
export function inkChecksum(ink: InkPage): string {
  const text = JSON.stringify(ink.strokes.map((s) => [s.id, s.tool, s.color, s.size, s.points.length, s.videoTime]));
  let h1 = 0x811c9dc5;
  let h2 = 0x01000193 ^ text.length;
  for (let i = 0; i < text.length; i++) {
    const c = text.charCodeAt(i);
    h1 = Math.imul(h1 ^ c, 0x01000193) >>> 0;
    h2 = Math.imul(h2 ^ c, 0x5bd1e995) >>> 0;
  }
  return h1.toString(16).padStart(8, '0') + h2.toString(16).padStart(8, '0');
}

/**
 * 충돌 병합: 획은 id로 식별되는 추가 전용 데이터로 보고 합집합을 만든다.
 * 삭제는 deletedIds(양쪽 중 한 쪽에서 지운 획)로 반영한다.
 */
export function mergeInk(local: InkPage, server: InkPage, deletedIds: ReadonlySet<string> = new Set()): InkPage {
  const byId = new Map<string, Stroke>();
  for (const s of server.strokes) byId.set(s.id, s);
  for (const s of local.strokes) byId.set(s.id, s);
  const strokes = [...byId.values()]
    .filter((s) => !deletedIds.has(s.id))
    .sort((a, b) => a.createdAt - b.createdAt || a.id.localeCompare(b.id));
  return { version: INK_FORMAT_VERSION, pageId: local.pageId, strokes };
}

/** 기기 유형 추정 (UA + 화면 크기). 서버 정책 키로 쓰인다. */
export function guessDeviceType(ua: string, shortSidePx: number): DeviceType {
  const mobile = /Android|iPhone|iPad|iPod|Mobile/i.test(ua);
  const ipadDesktopUa = /Macintosh/.test(ua) && /Mobile|Safari/.test(ua) && shortSidePx >= 700 && shortSidePx < 1100;
  if (!mobile && !ipadDesktopUa) return 'pc';
  return shortSidePx >= 600 ? 'tablet' : 'phone';
}
