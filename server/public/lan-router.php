<?php
declare(strict_types=1);

/**
 * 사내 랜 공유용 라우터 (PHP 내장 서버, 한 주소에서 웹 + API)
 *   php -S 0.0.0.0:8080 -t apps/web/dist server/public/lan-router.php
 *   /api/*        → 해설북 API (config: 환경변수 HSB_CONFIG, 랜은 server/config.lan.php)
 *   있는 파일      → 웹 정적 파일(내장 서버가 그대로 보냄)
 *   그 밖의 경로   → index.html (앱 내부 주소: /read/…, /login …)
 */

$uri = (string) parse_url($_SERVER['REQUEST_URI'] ?? '/', PHP_URL_PATH);
// 웹을 VITE_BASE=/ebook/ 로 빌드했어도 로컬(:5301)에서 열리게 — /ebook/… 를 / … 로 본다 (2026-11-11)
$prefixed = false;
if ($uri === '/' && str_contains((string) @file_get_contents($_SERVER['DOCUMENT_ROOT'] . '/index.html'), '"/ebook/')) {
    header('Location: /ebook/');                        // 「로컬 해설북 열기」(/) → 빌드 기준 경로로
    return true;
}
if ($uri === '/ebook' || str_starts_with($uri, '/ebook/')) {
    $uri = substr($uri, 6) ?: '/';
    $prefixed = true;
    if ($uri === '/api' || str_starts_with($uri, '/api/')) {
        $_SERVER['REQUEST_URI'] = $uri . (isset($_SERVER['QUERY_STRING']) && $_SERVER['QUERY_STRING'] !== '' ? '?' . $_SERVER['QUERY_STRING'] : '');
    }
}

if ($uri === '/api' || str_starts_with($uri, '/api/')) {
    $_SERVER['SCRIPT_NAME'] = '/api/index.php';       // API 기준 경로 = /api
    require dirname(__DIR__) . '/src/bootstrap.php';
    Hsb\handle(Hsb\Request::fromGlobals())->send();
    return true;
}

$root = (string) realpath($_SERVER['DOCUMENT_ROOT']);
$file = realpath($root . $uri);
if ($file !== false && is_file($file) && str_starts_with($file, $root)) {
    if (!$prefixed) {
        return false;                                   // 내장 서버가 정적 파일로
    }
    $types = ['js' => 'text/javascript', 'css' => 'text/css', 'svg' => 'image/svg+xml', 'json' => 'application/json',
              'webmanifest' => 'application/manifest+json', 'png' => 'image/png', 'webp' => 'image/webp',
              'woff2' => 'font/woff2', 'html' => 'text/html; charset=utf-8'];
    $ext = strtolower(pathinfo($file, PATHINFO_EXTENSION));
    header('Content-Type: ' . ($types[$ext] ?? 'application/octet-stream'));
    readfile($file);
    return true;
}
if ($prefixed && !str_contains((string) @file_get_contents($root . '/index.html'), '"/ebook/')) {
    $qs = (string) ($_SERVER['QUERY_STRING'] ?? '');
    header('Location: ' . $uri . ($qs !== '' ? '?' . $qs : ''));   // 예전 /ebook/… 주소 → 지금 빌드(/) 주소로
    return true;
}
header('Content-Type: text/html; charset=utf-8');
header('Cache-Control: no-cache');
readfile($root . '/index.html');
return true;
