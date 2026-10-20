import { StrictMode, Suspense, lazy, useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter, Link, NavLink, Route, Routes, useNavigate } from 'react-router-dom';
import './styles.css';
import { hasSession, logout, onAuthChange } from './lib/api';
import { AuthCallback } from './pages/AuthCallback';
import { Download } from './pages/Download';
import { Library } from './pages/Library';
import { Login } from './pages/Login';

// 리더(필기 엔진·KaTeX)는 따로 받아 첫 화면을 가볍게
const Reader = lazy(() => import('./pages/Reader').then((m) => ({ default: m.Reader })));

function Shell({ children }: { children: React.ReactNode }) {
  const [loggedIn, setLoggedIn] = useState(hasSession());
  const nav = useNavigate();
  useEffect(() => onAuthChange((ok, reason) => {
    setLoggedIn(ok);
    if (!ok && reason) { alert(reason); nav('/login'); }
  }), [nav]);
  return (
    <>
      <header className="topbar">
        <Link to="/" className="brand">해설북</Link>
        <nav>
          <NavLink to="/" end>교재</NavLink>
          <NavLink to="/download">앱 다운로드</NavLink>
          {loggedIn ? <button className="link" onClick={() => void logout()}>로그아웃</button> : <NavLink to="/login">로그인</NavLink>}
        </nav>
      </header>
      {children}
    </>
  );
}

function App() {
  return (
    <BrowserRouter basename={import.meta.env.BASE_URL.replace(/\/$/, '')}>
      <Routes>
        <Route path="/read/:bookId" element={<Suspense fallback={<div className="center-msg"><p>교재를 여는 중…</p></div>}><Reader /></Suspense>} />
        <Route path="/" element={<Shell><Library /></Shell>} />
        <Route path="/login" element={<Shell><Login /></Shell>} />
        <Route path="/auth/callback" element={<Shell><AuthCallback /></Shell>} />
        <Route path="/download" element={<Shell><Download /></Shell>} />
        <Route path="*" element={<Shell><div className="center-msg"><p>없는 페이지입니다</p><Link to="/">교재 목록</Link></div></Shell>} />
      </Routes>
    </BrowserRouter>
  );
}

/** Capacitor 셸: haeseolbook://auth/callback?code=… 딥링크 → 웹의 /auth/callback 으로 (Tauri 는 Rust 쪽에서 처리) */
type CapWindow = Window & { Capacitor?: { Plugins?: { App?: { addListener: (e: string, cb: (d: { url: string }) => void) => void } } } };
(window as CapWindow).Capacitor?.Plugins?.App?.addListener('appUrlOpen', ({ url }) => {
  const m = /^haeseolbook:\/\/auth\/callback\?code=([\w-]+)$/.exec(url);
  if (m) location.href = `${import.meta.env.BASE_URL}auth/callback?code=${m[1]}`;
});

createRoot(document.getElementById('root')!).render(<StrictMode><App /></StrictMode>);
