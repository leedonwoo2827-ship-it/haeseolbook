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

if ($uri === '/api' || str_starts_with($uri, '/api/')) {
    $_SERVER['SCRIPT_NAME'] = '/api/index.php';       // API 기준 경로 = /api
    require dirname(__DIR__) . '/src/bootstrap.php';
    Hsb\handle(Hsb\Request::fromGlobals())->send();
    return true;
}

$root = (string) realpath($_SERVER['DOCUMENT_ROOT']);
$file = realpath($root . $uri);
if ($file !== false && is_file($file) && str_starts_with($file, $root)) {
    return false;                                       // 내장 서버가 정적 파일로
}
header('Content-Type: text/html; charset=utf-8');
header('Cache-Control: no-cache');
readfile($root . '/index.html');
return true;
