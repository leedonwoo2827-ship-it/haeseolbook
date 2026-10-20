# 해설북 — 기술직 공무원 기출 + 유튜브 해설영상 연동 필기 이북

기출 시험지 **원문을 그대로** 보여 주고, 그 위에 펜으로 필기한다. 문항을 누르면 **그 문항의 유튜브 해설 구간**이 재생되고, 영상이 진행되면 원문이 따라간다.

- IP 허브에 붙는 **아이템 패키지(`ebook-video`)**로 만들어진다.
- 출판사 사이트(axexam.mycafe24.com, 그누보드)에 선별해 업로드한다.
- 모든 교재는 무료다.

## 바로 쓰기 (Windows)

| 파일 | 하는 일 |
|---|---|
| `setup.bat` | 처음 한 번. 파이썬 가상환경, SuperTonic3 목소리 모델(약 400MB), 포터블 PHP, 웹 빌드, 로컬 DB |
| `youtube-login.bat` | 처음 한 번. 이 폴더 전용 Chrome 프로필로 유튜브에 로그인하고 채널 선택 |
| `run.bat` | 스튜디오 대시보드(http://127.0.0.1:5300)와 로컬 해설북(http://127.0.0.1:8080)을 연다. `run.bat <명령>`은 CLI |
| `lan-run.bat` | 사내 랜 공유. 이 PC의 `http://<랜 IP>:8080`을 출력하고, 이메일만 입력하면 입장(검수 모드) |

준비물(PATH): Python 3.11 이상, Node 20 이상, ffmpeg(`winget install Gyan.FFmpeg`), Google Chrome, `claude` CLI(로그인).
다른 폴더나 저장소에는 의존하지 않는다.

## 해설북 스튜디오: 기출 → 판서 해설 롱폼 영상 → 유튜브 → 이북 연동

`_assets/<연도>/`의 기출 PDF와 최종정답 PDF(`_assets/index.json`)로 회차마다 영상 한 편과 이북 한 권을 만든다.

| 단계 | 하는 일 | 결과 (`studio/jobs/<작업>/`) |
|---|---|---|
| s0 원문 | 페이지 WebP, 문항 영역(1단·2단 자동), 공식 정답, 문항 크롭 | `book/`, `boards/crop/` |
| s1 대본 | Claude CLI가 문항별 해설 내레이션과 이북 해설 글을 쓴다. 정답은 공식 정답표로 고정 | `script/qNN.json`, `book/solutions.json` |
| s2 판서 | Claude가 문장마다 원문의 어디에 무엇을 그릴지 정한다 | `script/qNN.marks.json` |
| s3 목소리 | SuperTonic3 F1, 문장 캐시 | `audio/narration.wav`, `timing.json` |
| s4 화면 | 「단정 스케치북」 테마. 원문 전체 위에 판서가 말에 맞춰 그려진다 | `boards/frames/`, `frames.json` |
| s5 영상 | 1920×1080 mp4, 자막, 썸네일, 유튜브 챕터 | `out/<작업>.mp4`, `out/chapters.txt` |
| s6 업로드 | 유튜브 Studio 자동 입력(기본 일부공개) | `state.json`의 `posted` |
| s7 연동 | 문항별 영상 구간과 판서 포인터를 패키지로 만들어 로컬 해설북에 게시 | `content/dist/*.hsbpkg.zip` |

판서 표시:
- 형광펜: 핵심 조건
- 물결 밑줄: 키워드
- ✓ / ✗: 보기나 ㄱ·ㄴ·ㄷ 판정
- 빨간 원: 정답

이북에서는 영상이 재생되는 동안 빨간 점이 판서 위치를 따라간다.

```bat
run.bat new --year 2025                     :: 작업 만들기
run.bat make --job 2025-g9-computer         :: s0~s5 영상까지
run.bat post --job 2025-g9-computer         :: 일부공개 업로드
run.bat link --job 2025-g9-computer         :: 이북 연동
run.bat batch --years 2018-2024 --post      :: 여러 해를 차례로 (업로드·연동까지)
```

**끊겨도 이어서 진행된다:**
- 문항, 문장, 화면 단위로 저장한다. 같은 명령을 다시 실행하면 끝난 것은 건너뛴다.
- Claude 사용 한도(5시간·주간)에 걸리면 재설정 시각까지 기다렸다 이어서 한다. 최대 24시간, 60분마다 확인하고, 그동안 절전을 막는다. 대시보드에 「⏸ 한도 대기」가 보인다.

## 구성

```
packages/shared   도메인 스키마·순수 함수(segmentAt, cueAt, mergeInk, inkChecksum) — 웹·테스트 공용
apps/web          PWA 리더 (Vite + React) — 모든 OS 의 브라우저·홈 화면 설치·앱 셸이 이 한 벌을 쓴다
server            API (PHP 8.1+ / MySQL, 프레임워크·Composer 없음 → Cafe24 FTP 배포)
apps/desktop      Tauri 2 셸 (Windows/macOS/Linux) — 사이트 URL 로드, 딥링크, 캡처 차단
apps/mobile       Capacitor 6 셸 (iOS/Android) — 사이트 URL 로드, 딥링크
tools/pipeline    기출 PDF → 페이지 WebP·문항 영역·해설(DeepSeek 선택)·패키지
studio            해설 영상 스튜디오 (python -m studio · 대시보드 :5300) — TTS·렌더·유튜브 업로드 내장
_assets           기출 원문 PDF·최종정답 (연도별, 저장소 제외)
deploy/cafe24     Cafe24 업로드 묶음 생성
e2e               Playwright E2E
docs              기기 무관 서비스 연구
_plan             계획 문서 (로컬 전용, 저장소 제외)
```

## 콘텐츠 만들기 (기출 1회차 → 패키지)

```bash
P=tools/pipeline; B=content/build/2025-g9-electric
python -I $P/render.py  content/raw/2025-전기이론.pdf $B --id 2025-g9-electric \
       --title "2025 국가직 9급 전기이론" --exam "국가직 9급" --subject "전기이론" --year 2025
python -I $P/regions.py content/raw/2025-전기이론.pdf $B --answers content/raw/2025-전기이론-정답.json   # {"1":3,...}
python -I $P/preview.py $B                 # _preview/*.png 로 문항 영역 검수
DEEPSEEK_API_KEY=sk-... python -I $P/explain.py $B   # (선택) 해설 초안 → solutions.draft.json → 검수 후 solutions.json
cp <AI 영상 매핑> $B/video_map.json         # 아래 형식
python -I $P/package.py $B --version 1.0.0 --out content/dist   # → IP 허브 아이템 .hsbpkg.zip
```

- 스캔본 PDF(텍스트 없음)는 OCR을 먼저 거쳐야 `regions.py`가 문항 번호를 찾는다.
- 국가직 시험지는 2단 편집이 기본이다(`--columns 2`). 일반 문제집은 `--columns 1`.

### 큰 문제집을 회차별로 나누기 (예: SQLD 1000제 = 50문항 × 20회차 = 교재 20권)

```bash
# 2회차가 PDF 13~24쪽, 문항 번호가 51번부터 이어지는 경우
B=content/build/sqld-1000-r02
python -I $P/render.py  content/raw/sqld-1000.pdf $B --pages 13-24 --id sqld-1000-r02 \
       --title "SQLD 1000제 2회" --exam "SQLD" --subject "SQL 개발자" --year 2026 --round "2회"
python -I $P/regions.py content/raw/sqld-1000.pdf $B --pages 13-24 --first 51 --columns 1 --answers content/raw/sqld-정답.json
```

- 문항 번호가 회차마다 1번부터 다시 시작하면 `--first`는 생략한다.
- 회사 콘텐츠(`content/`, PDF·영상·패키지)는 `.gitignore`로 저장소에 올라가지 않는다.

### video_map.json (AI 가 해설영상을 만들며 역으로 넘겨주는 좌표)

```json
[{ "no": 1, "youtubeId": "xxxxxxxxxxx", "startSec": 12.0, "endSec": 95.5,
   "pageNo": 1, "bbox": {"x":0.05,"y":0.09,"w":0.45,"h":0.18},
   "cues": [{"t": 15.2, "pageNo": 1, "x": 0.31, "y": 0.42}] }]
```

- `pageNo`와 `bbox`는 선택이다. 있으면 그 값이 문항 영역이 되고, 없으면 `regions.json`의 영역을 쓴다.
- `cues`도 선택이다. 원문 위 포인터 트랙으로, 리더에서 빨간 점이 영상 시각에 맞춰 움직인다.
- 좌표는 모두 페이지 기준 0–1이다.
- 영상 규격 권고: **가로 16:9, 회차당 한 편 + 문항별 챕터** (근거는 [docs/cross-device-research.md](docs/cross-device-research.md) §5).

## 로컬 개발

```bash
npm install
npm run build:shared
# API (PHP 8.1+, pdo_sqlite·zip 확장). server/config.php 는 SQLite 개발 설정
php server/bin/hsb.php migrate
php -r 'require "server/src/bootstrap.php"; print_r(Hsb\Import\import_package("content/dist/sample-electric-1.0.0.hsbpkg.zip"));'
php -S localhost:8080 -t server/public server/public/index.php
# 웹
cp apps/web/.env.example apps/web/.env && npm run dev:web     # http://localhost:5173
```

샘플(자체 작성 문항, 실제 기출 아님)은 `python -I tools/pipeline/make_sample.py content/raw`로 만든다. 이어서 위 파이프라인을 돌리면 된다.

## 테스트

| 테스트 | 명령 | 결과 (2026-10-19) |
|---|---|---|
| shared 단위 | `npm test` | 7/7 |
| API 통합 (인증·기기 정책·SSO·서명 URL·필기 충돌·채점·패키지 위변조·CORS) | `php server/tests/run.php` | 58/58 |
| E2E (PC 필기→채점→태블릿 동기화, 폰 오프라인 필기→복구 동기화) | `cd e2e && npx playwright test` (API·웹 실행 중) | 2/2 |

## 출판사 사이트(Cafe24) 배포

```bash
HSB_ROOT=/home/hosting_users/<cafe24아이디>/hsb ./deploy/cafe24/build.sh
```

1. `deploy/out/hsb/`를 FTP 홈(웹 루트 밖)에, `deploy/out/www/exam/ebook/`를 `www/exam/ebook/`에 올린다.
2. `hsb/config.example.php`를 `config.php`로 복사해 아래 값을 채운다.
   - MySQL 접속 정보
   - `jwt_secret`·`asset_secret`·`admin_token`(각 32자 이상 랜덤)
   - `public_api_url`(`https://axexam.mycafe24.com/exam/ebook/api`)
   - `web_url`(`https://axexam.mycafe24.com/exam/ebook`)
   - `g5_common`(그누보드 `common.php` 절대경로 → "XAMpass 회원으로 로그인")
3. Cafe24 DB 관리(phpMyAdmin)에서 `schema.mysql.sql`을 실행한다. 테이블은 모두 `hsb_` 접두어라 그누보드 테이블과 섞이지 않는다.
4. `/exam/ebook/api/health`를 확인한 뒤 `/exam/ebook/api/admin`에서 IP 허브 패키지를 업로드한다. 게시와 비공개도 여기서 바꾼다.

배포 전 확인할 것:
- 호스팅 PHP 버전이 **8.1 이상**인지(Cafe24 관리에서 변경 가능)
- `zip`·`pdo_mysql`·`curl` 확장
- `upload_max_filesize` ≥ 패키지 크기
- HTTPS(서비스 워커·PWA 설치에 필요)

## 데스크톱·모바일 앱

- 데스크톱: `.github/workflows/desktop.yml`이 태그 `v*`에서 Windows/macOS/Linux 설치 파일을 빌드한다.
- 모바일: `apps/mobile`에서 `npm i && npx cap add android|ios`를 실행한다. Android Studio나 Xcode가 필요하다.
- 두 셸 모두 사이트 URL을 띄우는 얇은 래퍼라, 웹을 배포하면 앱에도 바로 반영된다.
