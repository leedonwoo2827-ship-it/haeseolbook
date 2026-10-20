#!/usr/bin/env bash
# Cafe24(리눅스 + PHP + MySQL, FTP 배포)용 업로드 묶음을 만든다.
#
#   HSB_ROOT=/home/hosting_users/<cafe24아이디>/hsb ./deploy/cafe24/build.sh
#
# 결과: deploy/out/
#   hsb/                    → FTP 홈(/home/hosting_users/<id>/)에 올림 (웹 루트 밖)
#   www/exam/ebook/         → FTP www/exam/ebook/ 에 올림 (PWA)
#   www/exam/ebook/api/     → API 진입점 (index.php + .htaccess)
set -euo pipefail
export MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL="*"  # Windows Git Bash 에서 /exam/... 경로 변환 방지

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OUT="$ROOT/deploy/out"
BASE="${WEB_BASE:-/exam/ebook/}"
: "${HSB_ROOT:?HSB_ROOT 를 지정하세요 (예: /home/hosting_users/axexam/hsb)}"

rm -rf "$OUT"
mkdir -p "$OUT/hsb" "$OUT/www${BASE}api"

# 1) 웹(PWA) — 같은 도메인의 /exam/ebook/api 를 부른다
( cd "$ROOT" && npm run build:shared >/dev/null )
( cd "$ROOT/apps/web" && VITE_BASE="$BASE" VITE_API_URL="${BASE}api" npx vite build --mode production >/dev/null )
cp -R "$ROOT/apps/web/dist/." "$OUT/www${BASE}"
cp "$ROOT/deploy/cafe24/web.htaccess" "$OUT/www${BASE}.htaccess"

# 2) API 진입점
sed "s#__HSB_ROOT__#${HSB_ROOT}#" "$ROOT/deploy/cafe24/api-index.php" > "$OUT/www${BASE}api/index.php"
cp "$ROOT/server/public/.htaccess" "$OUT/www${BASE}api/.htaccess"

# 3) 서버 코드 (웹 루트 밖)
cp -R "$ROOT/server/src" "$ROOT/server/bin" "$OUT/hsb/"
cp "$ROOT/server/schema.mysql.sql" "$ROOT/server/config.example.php" "$OUT/hsb/"
mkdir -p "$OUT/hsb/storage"
printf 'Deny from all\n' > "$OUT/hsb/.htaccess"   # 혹시 웹 루트 안에 올려도 노출되지 않게

cat <<EOF
업로드 묶음 → $OUT
 1. hsb/            → FTP ${HSB_ROOT}
 2. www/exam/ebook/ → FTP www/exam/ebook/
 3. ${HSB_ROOT}/config.example.php 를 config.php 로 복사해 값 입력 (DB·비밀키·g5_common·admin_token)
 4. Cafe24 DB 관리(phpMyAdmin)에서 schema.mysql.sql 실행
 5. https://<도메인>${BASE}api/health → {"ok":true} 확인, ${BASE}api/admin 에서 패키지 업로드
EOF
