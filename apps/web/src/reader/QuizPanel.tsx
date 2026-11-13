import { useMemo } from 'react';
import type { Quiz, Solution, Stroke, VideoSegment } from '@hsb/shared';
import type { Attempt } from '../lib/api';
import { renderMarkdown } from '../lib/markdown';

const CIRCLED = '①②③④⑤';

export type PanelTab = 'quiz' | 'notes' | 'wrong';

interface Props {
  /** all = 예전(탭·번호·해설 한 칸) · nav = 탭·번호만(실기 왼쪽) · solution = 고른 문항의 해설만(실기 오른쪽) */
  part?: 'all' | 'nav' | 'solution';
  tab: PanelTab;
  onTab: (t: PanelTab) => void;
  quizzes: Quiz[];
  solutions: Map<string, Solution>;
  segments: Map<string, VideoSegment>;
  attempts: Map<string, Attempt>;
  activeQuizId: string | null;
  lastResult: { quizId: string; chosen: number; correct: boolean } | null;
  notes: { pageId: string; pageNo: number; stroke: Stroke }[];
  onSelect: (quizId: string, seek: boolean) => void;
  onAnswer: (quizId: string, chosen: number) => void;
  onNote: (pageId: string, stroke: Stroke) => void;
}

const fmt = (sec: number) => `${Math.floor(sec / 60)}:${String(Math.floor(sec % 60)).padStart(2, '0')}`;

export function QuizPanel(p: Props) {
  const quiz = p.quizzes.find((q) => q.id === p.activeQuizId) ?? null;
  const attempt = quiz ? p.attempts.get(quiz.id) : undefined;
  const result = quiz && p.lastResult?.quizId === quiz.id ? p.lastResult : null;
  const answered = !!result || !!attempt;
  // 보기가 없는 문항(실기 작업형 등)은 채점 없이 해설을 바로 연다
  const task = !!quiz && quiz.choiceCount === 0;
  const solutionHtml = useMemo(() => {
    const s = quiz && p.solutions.get(quiz.id);
    return s ? renderMarkdown(s.markdown) : '';
  }, [quiz, p.solutions]);
  const wrong = p.quizzes.filter((q) => p.attempts.get(q.id)?.everWrong);
  const seg = quiz ? p.segments.get(quiz.id) : undefined;
  const part = p.part ?? 'all';

  if (part === 'solution') {
    // 실기 오른쪽 칸 — 고른 문항의 해설(그림 포함)만
    return (
      <div className="panel sol-panel">
        {!quiz && <p className="muted">왼쪽에서 문항 번호를 누르거나 원문의 문항을 누르면 여기에 해설이 나옵니다.</p>}
        {quiz && (
          <div className="quiz-card">
            <div className="quiz-head">
              <b>{quiz.no}번</b>
              {seg && <button className="link" onClick={() => p.onSelect(quiz.id, true)}>▶ 해설 영상 {fmt(seg.startSec)}–{fmt(seg.endSec)}</button>}
            </div>
            {solutionHtml ? <div className="solution" dangerouslySetInnerHTML={{ __html: solutionHtml }} /> : <p className="muted">해설 준비 중입니다.</p>}
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="panel">
      <div className="tabs" role="tablist">
        {([['quiz', '문항·해설'], ['notes', `필기 타임라인 ${p.notes.length || ''}`], ['wrong', `오답노트 ${wrong.length || ''}`]] as const).map(([k, label]) => (
          <button key={k} role="tab" aria-selected={p.tab === k} className={p.tab === k ? 'on' : ''} onClick={() => p.onTab(k)}>{label}</button>
        ))}
      </div>

      {p.tab === 'quiz' && (
        <div className="panel-body">
          <div className="quiz-grid">
            {p.quizzes.map((q) => {
              const a = p.attempts.get(q.id);
              return (
                <button key={q.id} className={`qno ${q.id === p.activeQuizId ? 'active' : ''} ${a ? (a.correct ? 'ok' : 'bad') : ''}`}
                  onClick={() => p.onSelect(q.id, true)} title={p.segments.has(q.id) ? '해설 영상 있음' : ''}>
                  {q.no}{p.segments.has(q.id) && <i className="dot" />}
                </button>
              );
            })}
          </div>
          {!quiz && part === 'all' && <p className="muted">문항 번호를 누르거나 원문의 문항을 탭하면 해설 영상이 그 구간부터 재생됩니다.</p>}
          {quiz && part === 'all' && (
            <div className="quiz-card">
              <div className="quiz-head">
                <b>{quiz.no}번</b>
                {seg && <button className="link" onClick={() => p.onSelect(quiz.id, true)}>▶ 해설 영상 {fmt(seg.startSec)}–{fmt(seg.endSec)}</button>}
              </div>
              <div className="choices">
                {Array.from({ length: quiz.choiceCount }, (_, i) => i + 1).map((n) => {
                  const chosen = result?.chosen === n || (!result && attempt?.chosen === n);
                  const cls = answered && n === quiz.answer ? 'correct' : chosen ? 'wrong' : '';
                  return (
                    <button key={n} className={`choice ${cls}`} onClick={() => p.onAnswer(quiz.id, n)} aria-label={`${n}번 보기 선택`}>
                      {CIRCLED[n - 1]}
                    </button>
                  );
                })}
              </div>
              {answered && (
                <p className={(result ?? attempt)!.correct ? 'verdict ok' : 'verdict bad'}>
                  {(result ?? attempt)!.correct ? '정답입니다' : `오답 — 정답은 ${CIRCLED[quiz.answer - 1]}`}
                </p>
              )}
              {(answered || task) && solutionHtml && <div className="solution" dangerouslySetInnerHTML={{ __html: solutionHtml }} />}
              {(answered || task) && !solutionHtml && <p className="muted">해설 준비 중입니다.</p>}
              {!answered && !task && <p className="muted">보기를 고르면 채점과 해설이 열립니다. 원문 위에 풀이를 먼저 써 보세요.</p>}
            </div>
          )}
        </div>
      )}

      {p.tab === 'notes' && (
        <div className="panel-body">
          {!p.notes.length && <p className="muted">영상을 보며 쓴 필기가 여기에 시간순으로 모입니다. 누르면 그 장면으로 이동합니다.</p>}
          <ul className="notes">
            {p.notes.map((n) => (
              <li key={n.stroke.id}>
                <button onClick={() => p.onNote(n.pageId, n.stroke)}>
                  <span className="swatch" style={{ background: n.stroke.color }} />
                  <span>{fmt(n.stroke.videoTime!)}</span>
                  <span className="muted">{n.pageNo}쪽 · {n.stroke.tool === 'pen' ? '펜' : '형광펜'}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      {p.tab === 'wrong' && (
        <div className="panel-body">
          {!wrong.length && <p className="muted">틀린 문항이 여기에 모입니다.</p>}
          <ul className="notes">
            {wrong.map((q) => (
              <li key={q.id}>
                <button onClick={() => { p.onTab('quiz'); p.onSelect(q.id, true); }}>
                  <b>{q.no}번</b>
                  <span className="muted">{p.attempts.get(q.id)!.correct ? '다시 풀어 맞힘' : '아직 오답'} · {p.attempts.get(q.id)!.tries}회</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
