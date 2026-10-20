import { useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { exchangeCode } from '../lib/api';
import { takeNext } from './Login';

/** OAuth·사이트 회원 로그인 완료 → 1회용 코드를 토큰으로 교환 (웹 리다이렉트, 앱 딥링크 공통) */
export function AuthCallback() {
  const [sp] = useSearchParams();
  const nav = useNavigate();
  const [err, setErr] = useState<string | null>(null);
  const done = useRef(false);

  useEffect(() => {
    const code = sp.get('code');
    if (done.current) return;
    done.current = true;
    if (!code) { setErr('로그인 정보가 없습니다'); return; }
    exchangeCode(code)
      .then((replaced) => {
        if (replaced.length) alert('같은 종류의 다른 기기에서 로그아웃되었습니다 (기기 종류별 1대).');
        nav(takeNext(), { replace: true });
      })
      .catch((e: Error) => setErr(e.message));
  }, [sp, nav]);

  return (
    <div className="center-msg">
      {err ? <><p>{err}</p><Link to="/login">다시 로그인</Link></> : <p>로그인 중…</p>}
    </div>
  );
}
