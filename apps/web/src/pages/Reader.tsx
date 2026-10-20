import 'katex/dist/katex.min.css';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { cueAt, segmentAt, type BookManifest, type Stroke } from '@hsb/shared';
import { ApiError, getManifest, getMe, hasSession, listAttempts, submitAttempt, type Attempt } from '../lib/api';
import { loadManifest, saveManifest } from '../lib/db';
import { InkSync } from '../lib/sync';
import { useYouTube } from '../lib/youtube';
import { HIGHLIGHT_COLORS, HIGHLIGHT_SIZE, PEN_COLORS, PEN_SIZES, type Tool } from '../reader/ink';
import { PageView } from '../reader/PageView';
import { QuizPanel, type PanelTab } from '../reader/QuizPanel';

interface HistoryOp { pageId: string; before: Stroke[]; after: Stroke[] }

const SIDE_KEY = 'hsb.sideWidth';
const SIDE_MIN = 320;

/** 영상·문항 패널 폭 조절: 경계를 끌어서 넓히고, 두 번 누르면 기본 폭으로 */
function Splitter({ onWidth }: { onWidth: (w: number | null) => void }) {
  const onPointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    e.preventDefault();
    const el = e.currentTarget;
    el.setPointerCapture(e.pointerId);
    const move = (ev: PointerEvent) => onWidth(Math.round(Math.min(Math.max(ev.clientX, SIDE_MIN), window.innerWidth - 420)));
    const up = () => { el.removeEventListener('pointermove', move); el.removeEventListener('pointerup', up); };
    el.addEventListener('pointermove', move);
    el.addEventListener('pointerup', up);
  };
  return <div className="splitter" role="separator" aria-orientation="vertical" aria-label="영상 패널 폭 조절 (두 번 누르면 기본 폭)"
    onPointerDown={onPointerDown} onDoubleClick={() => onWidth(null)} />;
}

/** 스크롤 영역 안에서 페이지의 위치(스크롤 기준). offsetTop 은 위쪽 도구 막대까지 더해져 문항이 잘렸다 */
function pageTop(scroller: HTMLElement, page: HTMLElement): number {
  return scroller.scrollTop + page.getBoundingClientRect().top - scroller.getBoundingClientRect().top;
}

const SYNC_LABEL = { idle: '', saving: '저장 중…', saved: '저장됨', offline: '오프라인 · 기기에 저장됨', error: '동기화 오류 · 기기에 저장됨' } as const;

export function Reader() {
  const { bookId = '' } = useParams();
  const nav = useNavigate();
  const [m, setM] = useState<BookManifest | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [offline, setOffline] = useState(false);
  const [sync, setSync] = useState<InkSync | null>(null);
  const [, bump] = useState(0);

  const [tool, setTool] = useState<Tool>('pen');
  const [penColor, setPenColor] = useState(PEN_COLORS[1]);
  const [hlColor, setHlColor] = useState(HIGHLIGHT_COLORS[0]);
  const [penSize, setPenSize] = useState(PEN_SIZES[1]);
  const [fingerDraw, setFingerDraw] = useState(true);
  const [follow, setFollow] = useState(true);
  const [tab, setTab] = useState<PanelTab>('quiz');
  const [activeQuizId, setActiveQuizId] = useState<string | null>(null);
  const [videoId, setVideoId] = useState<string | null>(null);
  const [attempts, setAttempts] = useState(new Map<string, Attempt>());
  const [watermark, setWatermark] = useState('');
  const [lastResult, setLastResult] = useState<{ quizId: string; chosen: number; correct: boolean } | null>(null);
  const undo = useRef<HistoryOp[]>([]);
  const redo = useRef<HistoryOp[]>([]);

  const scroller = useRef<HTMLDivElement>(null);
  const [sideW, setSideW] = useState<number | null>(() => {
    try { const v = Number(localStorage.getItem(SIDE_KEY)); return v >= SIDE_MIN ? v : null; } catch { return null; }
  });
  const playerBox = useRef<HTMLDivElement>(null);
  const player = useYouTube(playerBox, videoId);
  const playerRef = useRef(player);
  playerRef.current = player;

  // ---------- 로드 ----------
  useEffect(() => {
    if (!hasSession()) { nav(`/login?next=${encodeURIComponent(`/read/${bookId}`)}`); return; }
    let s: InkSync | null = null;
    let off = () => {};
    (async () => {
      let manifest: BookManifest | undefined;
      try {
        manifest = await getManifest(bookId);
        await saveManifest(manifest).catch(() => {});
      } catch (e) {
        if (e instanceof ApiError && e.status !== 0 && navigator.onLine) { setErr(e.message); return; }
        manifest = await loadManifest(bookId);
        if (!manifest) { setErr('오프라인입니다. 한 번 이상 온라인에서 연 교재만 볼 수 있습니다.'); return; }
        setOffline(true);
      }
      setM(manifest);
      setVideoId(manifest.videoSegments[0]?.youtubeId ?? null);
      s = new InkSync(bookId);
      off = s.subscribe(() => bump((n) => n + 1));
      setSync(s);
      await s.start();
      getMe().then((me) => setWatermark(me.user.email)).catch(() => {});
      listAttempts(bookId).then((rows) => setAttempts(new Map(rows.map((a) => [a.quizId, a])))).catch(() => {});
    })();
    return () => { off(); s?.stop(); };
  }, [bookId, nav]);

  const quizzes = m?.quizzes ?? [];
  const segments = useMemo(() => new Map((m?.videoSegments ?? []).map((v) => [v.quizId, v])), [m]);
  const solutions = useMemo(() => new Map((m?.solutions ?? []).map((s) => [s.quizId, s])), [m]);
  const pageNoById = useMemo(() => new Map((m?.pages ?? []).map((p) => [p.id, p.pageNo])), [m]);
  const regionsByPage = useMemo(() => {
    const map = new Map<string, BookManifest['regions']>();
    for (const r of m?.regions ?? []) map.set(r.pageId, [...(map.get(r.pageId) ?? []), r]);
    return map;
  }, [m]);

  const scrollToQuiz = useCallback((quizId: string) => {
    const r = m?.regions.find((x) => x.quizId === quizId && x.kind === 'quiz');
    const el = r && scroller.current?.querySelector<HTMLElement>(`[data-page-id="${CSS.escape(r.pageId)}"]`);
    if (!r || !el || !scroller.current) return;
    const top = pageTop(scroller.current, el) + r.bbox.y * el.clientHeight - 24;
    scroller.current.scrollTo({ top, behavior: 'smooth' });
  }, [m]);

  // ---------- 영상 ↔ 원문 양방향 동기화 ----------
  const videoSegs = useMemo(() => (m?.videoSegments ?? []).filter((v) => v.youtubeId === videoId), [m, videoId]);
  const playingSeg = player.ready ? segmentAt(videoSegs, player.time) : null;
  useEffect(() => {
    if (!player.playing || !playingSeg || playingSeg.quizId === activeQuizId) return;
    setActiveQuizId(playingSeg.quizId);
    if (follow) scrollToQuiz(playingSeg.quizId);
  }, [player.playing, playingSeg, activeQuizId, follow, scrollToQuiz]);

  const cue = playingSeg ? cueAt(playingSeg.cues, player.time) : null;
  const cuePageId = cue ? m?.pages.find((p) => p.pageNo === cue.pageNo)?.id : undefined;

  const selectQuiz = useCallback((quizId: string, seek: boolean) => {
    setActiveQuizId(quizId);
    setTab('quiz');
    const seg = segments.get(quizId);
    if (seek && seg) {
      if (seg.youtubeId !== videoId) setVideoId(seg.youtubeId);
      playerRef.current.seek(seg.startSec);
    }
    scrollToQuiz(quizId);
  }, [segments, videoId, scrollToQuiz]);

  const onRegionTap = useCallback((quizId: string) => selectQuiz(quizId, true), [selectQuiz]);

  const onStrokeTap = useCallback((s: Stroke) => {
    if (s.videoTime !== null) playerRef.current.seek(s.videoTime);
  }, []);

  const onNote = useCallback((pageId: string, s: Stroke) => {
    const el = scroller.current?.querySelector<HTMLElement>(`[data-page-id="${CSS.escape(pageId)}"]`);
    if (el && scroller.current) {
      const y = Math.min(...s.points.map((pt) => pt[1]));
      scroller.current.scrollTo({ top: pageTop(scroller.current, el) + y * el.clientHeight - 80, behavior: 'smooth' });
    }
    if (s.videoTime !== null) playerRef.current.seek(s.videoTime);
  }, []);

  // ---------- 필기 ----------
  const onChange = useCallback((pageId: string, strokes: Stroke[], removed: string[]) => {
    if (!sync) return;
    undo.current.push({ pageId, before: sync.strokes(pageId), after: strokes });
    if (undo.current.length > 200) undo.current.shift();
    redo.current = [];
    void sync.setStrokes(pageId, strokes, removed);
  }, [sync]);

  const applyHistory = (from: React.MutableRefObject<HistoryOp[]>, to: React.MutableRefObject<HistoryOp[]>, dir: 'undo' | 'redo') => {
    const op = from.current.pop();
    if (!op || !sync) return;
    to.current.push(op);
    const next = dir === 'undo' ? op.before : op.after;
    const removed = sync.strokes(op.pageId).filter((s) => !next.some((n) => n.id === s.id)).map((s) => s.id);
    void sync.setStrokes(op.pageId, next, removed);
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!(e.ctrlKey || e.metaKey) || e.key.toLowerCase() !== 'z') return;
      e.preventDefault();
      if (e.shiftKey) applyHistory(redo, undo, 'redo'); else applyHistory(undo, redo, 'undo');
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  });

  const onPenDetected = useCallback(() => setFingerDraw(false), []);
  const videoTime = useCallback(() => playerRef.current.currentTime(), []);

  // ---------- 채점 ----------
  const onAnswer = async (quizId: string, chosen: number) => {
    const q = quizzes.find((x) => x.id === quizId);
    if (!q) return;
    const correct = q.answer === chosen;
    setLastResult({ quizId, chosen, correct });
    const prev = attempts.get(quizId);
    setAttempts(new Map(attempts).set(quizId, { quizId, chosen, correct, tries: (prev?.tries ?? 0) + 1, everWrong: (prev?.everWrong ?? false) || !correct }));
    submitAttempt(bookId, quizId, chosen).catch(() => {}); // 오프라인이면 로컬 채점만
  };

  const notes = useMemo(() => (sync?.allStrokes() ?? [])
    .filter((n) => n.stroke.videoTime !== null)
    .sort((a, b) => a.stroke.videoTime! - b.stroke.videoTime!)
    .map((n) => ({ ...n, pageNo: pageNoById.get(n.pageId) ?? 0 })),
  // eslint-disable-next-line react-hooks/exhaustive-deps
  [sync, sync?.state, pageNoById, bump]);

  if (err) return <div className="center-msg"><p>{err}</p><Link to="/">서재로</Link></div>;
  if (!m || !sync) return <div className="center-msg"><p>교재를 여는 중…</p></div>;

  const color = tool === 'highlighter' ? hlColor : penColor;
  const size = tool === 'highlighter' ? HIGHLIGHT_SIZE : penSize;

  return (
    <div className="reader">
      <header className="reader-top">
        <Link to="/" className="back" aria-label="서재로">←</Link>
        <div className="title"><b>{m.book.title}</b><small>{m.book.exam} · {m.book.subject}</small></div>
        <span className={`sync ${sync.state}`}>{offline ? '오프라인 모드' : SYNC_LABEL[sync.state]}</span>
      </header>

      <div className="reader-body" style={sideW ? ({ '--side-w': `${sideW}px` } as React.CSSProperties) : undefined}>
        <aside className="side">
          <div className="video">
            <div ref={playerBox} className="video-box" />
            {!videoId && <div className="video-empty">이 교재에는 아직 해설 영상이 없습니다</div>}
            {player.error && <div className="video-empty">{player.error}</div>}
          </div>
          <label className="follow"><input type="checkbox" checked={follow} onChange={(e) => setFollow(e.target.checked)} /> 영상 따라 원문 자동 이동</label>
          <QuizPanel
            tab={tab} onTab={setTab} quizzes={quizzes} solutions={solutions} segments={segments} attempts={attempts}
            activeQuizId={activeQuizId} lastResult={lastResult} notes={notes}
            onSelect={selectQuiz} onAnswer={onAnswer} onNote={onNote}
          />
        </aside>
        <Splitter onWidth={(w) => { setSideW(w); try { if (w) localStorage.setItem(SIDE_KEY, String(w)); else localStorage.removeItem(SIDE_KEY); } catch { /* 저장 불가 */ } }} />

        <main className="pages-col">
          <div className="toolbar" role="toolbar" aria-label="필기 도구">
            {([['view', '보기', '탭: 문항/필기 → 영상 이동'], ['pen', '펜', ''], ['highlighter', '형광펜', ''], ['eraser', '지우개', '획 단위']] as const).map(([t, label, tip]) => (
              <button key={t} className={tool === t ? 'on' : ''} onClick={() => setTool(t)} title={tip}>{label}</button>
            ))}
            <span className="sep" />
            {(tool === 'highlighter' ? HIGHLIGHT_COLORS : PEN_COLORS).map((c) => (
              <button key={c} className={`swatch-btn ${color === c ? 'on' : ''}`} style={{ background: c }} aria-label={`색 ${c}`}
                onClick={() => (tool === 'highlighter' ? setHlColor(c) : (setPenColor(c), tool !== 'pen' && setTool('pen')))} />
            ))}
            {tool === 'pen' && PEN_SIZES.map((s, i) => (
              <button key={s} className={`size-btn ${penSize === s ? 'on' : ''}`} onClick={() => setPenSize(s)} aria-label={`굵기 ${i + 1}`}>
                <i style={{ width: 4 + i * 4, height: 4 + i * 4 }} />
              </button>
            ))}
            <span className="sep" />
            <button onClick={() => applyHistory(undo, redo, 'undo')} aria-label="실행 취소">↶</button>
            <button onClick={() => applyHistory(redo, undo, 'redo')} aria-label="다시 실행">↷</button>
            <label className="finger" title="펜이 감지되면 자동으로 꺼집니다(손바닥 오인식 방지). 끄면 손가락으로 스크롤합니다.">
              <input type="checkbox" checked={fingerDraw} onChange={(e) => setFingerDraw(e.target.checked)} /> 손가락 필기
            </label>
          </div>
          <div ref={scroller} className="pages">
            {m.pages.map((pg) => (
              <PageView
                key={pg.id}
                page={pg}
                urls={m.imageUrls[pg.id]}
                regions={regionsByPage.get(pg.id) ?? []}
                strokes={sync.strokes(pg.id)}
                tool={tool}
                color={color}
                size={size}
                fingerDraw={fingerDraw}
                activeQuizId={activeQuizId}
                watermark={watermark}
                cue={cuePageId === pg.id ? cue : null}
                videoTime={videoTime}
                onPenDetected={onPenDetected}
                onChange={onChange}
                onRegionTap={onRegionTap}
                onStrokeTap={onStrokeTap}
                scroller={scroller}
              />
            ))}
            <p className="watermark-note">본 교재 이미지는 로그인한 사용자 전용으로 제공됩니다.</p>
          </div>
        </main>
      </div>
    </div>
  );
}
