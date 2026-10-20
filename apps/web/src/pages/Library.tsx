import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { hasSession, listBooks, type BookItem } from '../lib/api';

export function Library() {
  const [books, setBooks] = useState<BookItem[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const loggedIn = hasSession();

  useEffect(() => {
    listBooks().then(setBooks).catch((e: Error) => setErr(navigator.onLine ? e.message : '오프라인입니다. 내 서재의 교재는 열 수 있습니다.'));
  }, []);

  return (
    <div className="container">
      <section className="hero-sm">
        <h1>기출 원문 위에 쓰고, 문항별 해설 영상으로 바로</h1>
        <p>9급 기술직 공무원 기출을 원문 그대로 보면서 펜으로 풀고, 문항을 누르면 그 문항의 유튜브 해설 구간이 재생됩니다. 모든 교재는 무료입니다.</p>
      </section>

      {err && <p className="notice">{err}</p>}
      {!books && !err && <p className="muted">불러오는 중…</p>}
      {books && !books.length && <p className="muted">아직 공개된 교재가 없습니다.</p>}

      {books && books.some((b) => b.owned) && <h2 className="sec">내 서재</h2>}
      <div className="book-grid">
        {books?.filter((b) => b.owned).map((b) => <BookCard key={b.id} b={b} loggedIn={loggedIn} />)}
      </div>

      <h2 className="sec">전체 교재</h2>
      <div className="book-grid">
        {books?.filter((b) => !b.owned).map((b) => <BookCard key={b.id} b={b} loggedIn={loggedIn} />)}
      </div>
    </div>
  );
}

function BookCard({ b, loggedIn }: { b: BookItem; loggedIn: boolean }) {
  const to = loggedIn ? `/read/${b.id}` : `/login?next=${encodeURIComponent(`/read/${b.id}`)}`;
  return (
    <Link to={to} className="book">
      <div className="book-cover">
        <span className="exam">{b.exam}</span>
        <b>{b.subject}</b>
        <span>{b.year} · {b.round}</span>
      </div>
      <div className="book-meta">
        <b>{b.title}</b>
        <span className="muted">{b.quizCount}문항 · 해설영상 {b.videoCount ?? 0}개 · 무료</span>
        <span className="cta">{b.owned ? '이어서 보기' : '무료로 펼치기'}</span>
      </div>
    </Link>
  );
}
