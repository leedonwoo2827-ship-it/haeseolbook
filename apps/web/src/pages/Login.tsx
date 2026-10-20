import { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { devLogin, getProviders, inAppShell, loginUrl, openExternal, type Providers } from '../lib/api';

const NEXT_KEY = 'hsb.next';

/** 로그인 후 돌아갈 화면(앱 내부 경로만 허용) */
export function rememberNext(next: string | null) {
  try { sessionStorage.setItem(NEXT_KEY, next && next.startsWith('/') && !next.startsWith('//') ? next : '/'); } catch { /* 무시 */ }
}
export function takeNext(): string {
  try {
    const n = sessionStorage.getItem(NEXT_KEY) || '/';
    sessionStorage.removeItem(NEXT_KEY);
    return n;
  } catch { return '/'; }
}

export function Login() {
  const [sp] = useSearchParams();
  const nav = useNavigate();
  const [prov, setProv] = useState<Providers | null>(null);
  const [email, setEmail] = useState('');
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    rememberNext(sp.get('next'));
    getProviders().then(setProv).catch(() => setErr('서버에 연결할 수 없습니다'));
  }, [sp]);

  /** 앱 셸에서는 시스템 브라우저로 열고, 로그인 후 딥링크로 돌아온다 */
  const external = (e: React.MouseEvent<HTMLAnchorElement>) => {
    if (!inAppShell()) return;
    e.preventDefault();
    void openExternal(e.currentTarget.href);
  };

  const dev = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await devLogin(email);
      nav(takeNext(), { replace: true });
    } catch (x) {
      setErr((x as Error).message);
    }
  };

  return (
    <div className="container narrow">
      <div className="card login">
        <h1>로그인</h1>
        <p className="muted">필기와 채점 기록은 계정에 저장되어 PC·태블릿·폰(각 1대, 최대 3대)에서 이어집니다.</p>
        {err && <p className="notice">{err}</p>}
        {prov?.g5 && <a className="btn primary block" href={loginUrl('g5')}>XAMpass 회원으로 로그인</a>}
        {prov?.google && <a className="btn block" href={loginUrl('google')} onClick={external}>Google 로 계속</a>}
        {prov?.kakao && <a className="btn block kakao" href={loginUrl('kakao')} onClick={external}>카카오로 계속</a>}
        {prov && !prov.g5 && !prov.google && !prov.kakao && !prov.dev && <p className="muted">로그인 수단이 설정되지 않았습니다.</p>}
        {prov?.dev && (
          <form onSubmit={dev} className="dev">
            <label>검수용 이메일 로그인<input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@example.com" /></label>
            <button className="btn block">이메일로 로그인</button>
          </form>
        )}
      </div>
    </div>
  );
}
