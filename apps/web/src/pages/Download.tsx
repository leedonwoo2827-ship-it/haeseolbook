import { useState } from 'react';
import { Link } from 'react-router-dom';

/**
 * 앱 다운로드 안내 (books.solve.im/download 의 구성 차용: 히어로 → 기능 4종 → PC 앱 → 설치 가이드 → 모바일).
 * 기기마다 ①브라우저 ②PWA 설치 ③앱 세 경로로 같은 서재·필기에 접근한다.
 */
const RELEASES = (import.meta.env.VITE_RELEASES_URL as string | undefined) ?? '';

type Os = 'windows' | 'mac' | 'linux' | 'ipad' | 'android';
const OS_LABEL: Record<Os, string> = { windows: 'Windows', mac: 'macOS', linux: 'Linux', ipad: 'iPad·iPhone', android: 'Android' };

const GUIDE: Record<Os, { pwa: string[]; app: string[]; note?: string }> = {
  windows: {
    pwa: ['Edge 또는 Chrome 으로 이 사이트를 엽니다', '주소창 오른쪽 "앱 설치" 아이콘을 누릅니다', '시작 메뉴에 해설북이 생깁니다'],
    app: ['아래 Windows 설치 파일을 받습니다', '"Windows의 PC 보호" 경고가 뜨면 "추가 정보 → 실행"을 누릅니다', '설치 후 로그인하면 웹과 같은 서재가 열립니다'],
  },
  mac: {
    pwa: ['Safari 17 이상에서 이 사이트를 엽니다', '메뉴 "파일 → Dock에 추가"를 누릅니다'],
    app: ['Apple Silicon / Intel 에 맞는 DMG 를 받습니다', 'DMG 를 열어 해설북을 "응용 프로그램"으로 끌어 놓습니다', '처음 실행 시 "열기"를 한 번 더 누릅니다'],
  },
  linux: {
    pwa: ['Chrome/Chromium 에서 이 사이트를 엽니다', '주소창의 "설치" 아이콘을 누릅니다'],
    app: ['AppImage 를 받아 실행 권한을 줍니다 (chmod +x)', '또는 .deb 패키지를 설치합니다 (Ubuntu/Debian)'],
    note: 'Linux 는 화면 캡처 차단을 지원하지 않습니다. 펜 필압은 기기·드라이버에 따라 다를 수 있습니다.',
  },
  ipad: {
    pwa: ['Safari 로 이 사이트를 엽니다', '공유 버튼 → "홈 화면에 추가"', 'Apple Pencil 필압·손바닥 인식을 지원합니다'],
    app: ['App Store 출시 준비 중입니다'],
    note: '홈 화면 앱은 오래 쓰지 않으면 기기 저장소가 비워질 수 있습니다. 필기는 서버에 자동 저장되므로 다시 로그인하면 복원됩니다.',
  },
  android: {
    pwa: ['Chrome 으로 이 사이트를 엽니다', '메뉴 → "앱 설치" 또는 "홈 화면에 추가"', 'S Pen 필압을 지원합니다'],
    app: ['Google Play 출시 준비 중입니다'],
  },
};

const FEATURES = [
  ['원문 그대로', '기출 시험지를 원문 그대로 보여 줍니다. 그 위에 펜으로 바로 풉니다.'],
  ['문항별 해설 영상', '문항을 누르면 유튜브 해설의 그 문항 구간부터 재생됩니다. 영상이 진행되면 원문도 따라갑니다.'],
  ['필기 ↔ 영상 연결', '영상을 보며 쓴 필기를 누르면 그때 장면으로 돌아갑니다.'],
  ['기기 간 이어쓰기', 'PC·태블릿·폰 어디서나 같은 필기와 오답노트. 오프라인에서도 써지고 연결되면 동기화됩니다.'],
];

export function Download() {
  const [os, setOs] = useState<Os>(detectOs());
  const g = GUIDE[os];
  return (
    <div className="container">
      <section className="hero">
        <h1>해설북 앱으로 공부하세요</h1>
        <p>설치 없이 브라우저에서 바로 쓰고, 홈 화면에 설치하거나 PC 앱으로도 쓸 수 있습니다. 어느 방법이든 같은 서재·필기가 이어집니다.</p>
        <div className="row">
          <Link className="btn primary" to="/">브라우저에서 바로 시작</Link>
          <a className="btn" href="#install">설치 방법 보기</a>
        </div>
      </section>

      <section className="feature-grid">
        {FEATURES.map(([t, d]) => <div key={t} className="card"><b>{t}</b><p className="muted">{d}</p></div>)}
      </section>

      <section className="card">
        <h2>PC 에서도 편리하게</h2>
        <p className="muted">PC 앱은 웹과 같은 화면을 쓰고, 화면 캡처 차단(Windows·macOS)을 더합니다.</p>
        <div className="row wrap">
          <DlButton href={RELEASES && `${RELEASES}/haeseolbook_x64-setup.exe`} label="Windows 10+ (x64)" />
          <DlButton href={RELEASES && `${RELEASES}/haeseolbook_aarch64.dmg`} label="macOS Apple Silicon" />
          <DlButton href={RELEASES && `${RELEASES}/haeseolbook_x64.dmg`} label="macOS Intel" />
          <DlButton href={RELEASES && `${RELEASES}/haeseolbook_amd64.AppImage`} label="Linux AppImage" />
        </div>
      </section>

      <section className="card" id="install">
        <h2>기기별 설치 안내</h2>
        <div className="tabs inline" role="tablist">
          {(Object.keys(OS_LABEL) as Os[]).map((k) => (
            <button key={k} role="tab" aria-selected={os === k} className={os === k ? 'on' : ''} onClick={() => setOs(k)}>{OS_LABEL[k]}</button>
          ))}
        </div>
        <div className="guide">
          <div><h3>① 브라우저</h3><p className="muted">설치 없이 이 주소로 바로 이용합니다.</p></div>
          <div><h3>② 홈 화면·앱 설치 (PWA)</h3><ol>{g.pwa.map((s) => <li key={s}>{s}</li>)}</ol></div>
          <div><h3>③ 앱</h3><ol>{g.app.map((s) => <li key={s}>{s}</li>)}</ol></div>
        </div>
        {g.note && <p className="notice">{g.note}</p>}
      </section>
    </div>
  );
}

function DlButton({ href, label }: { href: string; label: string }) {
  return href ? <a className="btn" href={href}>{label}</a> : <span className="btn disabled" title="빌드 준비 중">{label} · 준비 중</span>;
}

function detectOs(): Os {
  const ua = navigator.userAgent;
  if (/Android/.test(ua)) return 'android';
  if (/iPhone|iPad/.test(ua) || (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1)) return 'ipad';
  if (/Mac OS X/.test(ua)) return 'mac';
  if (/Linux/.test(ua)) return 'linux';
  return 'windows';
}
