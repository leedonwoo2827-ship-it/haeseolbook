<?php
declare(strict_types=1);

/**
 * API 통합 테스트 (서버 없이 handle() 직접 호출, 임시 SQLite)
 *   php tests/run.php
 * 시드 데이터로 content/build/sample-electric 를 사용한다 (tools/pipeline 으로 생성).
 */

require dirname(__DIR__) . '/src/bootstrap.php';

use Hsb\Config;
use Hsb\Db;
use Hsb\Request;

$tmp = sys_get_temp_dir() . '/hsb-test-' . bin2hex(random_bytes(4));
mkdir("{$tmp}/storage", 0777, true);
$cfg = [
    'db_dsn' => "sqlite:{$tmp}/t.sqlite", 'db_user' => '', 'db_pass' => '',
    'jwt_secret' => str_repeat('j', 40), 'asset_secret' => str_repeat('a', 40),
    'public_api_url' => 'http://api.test', 'web_origin' => 'http://web.test', 'storage_dir' => "{$tmp}/storage",
    'allow_dev_login' => true, 'google' => null, 'kakao' => null, 'admin_token' => str_repeat('t', 40),
];
Config::load($cfg);
Db::reset();
Db::migrate(dirname(__DIR__) . '/schema.mysql.sql');
// 샘플은 tools/pipeline (make_sample → render → regions → package) 로 생성한다
$pkg = dirname(__DIR__, 2) . '/content/dist/sample-electric-1.0.0.hsbpkg.zip';
if (!is_file($pkg)) { fwrite(STDERR, "샘플 패키지가 없습니다: {$pkg}\n"); exit(1); }
Hsb\Import\import_package($pkg);

$fails = 0;
$n = 0;
function check(string $name, bool $ok, mixed $detail = null): void
{
    global $fails, $n;
    $n++;
    if ($ok) { echo "  ✔ {$name}\n"; return; }
    $fails++;
    echo "  ✘ {$name}" . ($detail !== null ? ' → ' . json_encode($detail, JSON_UNESCAPED_UNICODE) : '') . "\n";
}

/** @return array{0:int,1:mixed,2:array} */
function call(string $method, string $path, ?array $body = null, ?string $token = null, array $headers = []): array
{
    $u = parse_url($path);
    parse_str($u['query'] ?? '', $q);
    $h = array_change_key_case($headers);
    if ($token) $h['authorization'] = "Bearer {$token}";
    $res = Hsb\handle(new Request($method, $u['path'], $q, $h, $body === null ? '' : json_encode($body)));
    return [$res->status, $res->file ?? json_decode($res->body, true), $res->headers];
}

function uuid(): string
{
    $b = bin2hex(random_bytes(16));
    return sprintf('%s-%s-4%s-a%s-%s', substr($b, 0, 8), substr($b, 8, 4), substr($b, 13, 3), substr($b, 17, 3), substr($b, 20, 12));
}

echo "auth\n";
[$s, $b] = call('GET', '/auth/providers');
check('providers', $s === 200 && $b['dev'] === true && $b['google'] === false, $b);
[$s, $b] = call('POST', '/auth/dev-login', ['email' => 'bad', 'deviceId' => uuid(), 'deviceType' => 'pc']);
check('invalid email → 400', $s === 400);
$pc1 = uuid();
[$s, $login] = call('POST', '/auth/dev-login', ['email' => 'Kim@Test.kr', 'deviceId' => $pc1, 'deviceType' => 'pc']);
check('dev-login', $s === 200 && isset($login['accessToken'], $login['refreshToken']), $login);
$tok = $login['accessToken'];
[$s, $me] = call('GET', '/auth/me', null, $tok);
check('me (email normalized)', $s === 200 && $me['user']['email'] === 'kim@test.kr', $me);
[$s] = call('GET', '/auth/me');
check('me without token → 401', $s === 401);

$tab = uuid();
[, $tabLogin] = call('POST', '/auth/dev-login', ['email' => 'kim@test.kr', 'deviceId' => $tab, 'deviceType' => 'tablet']);
$phone = uuid();
call('POST', '/auth/dev-login', ['email' => 'kim@test.kr', 'deviceId' => $phone, 'deviceType' => 'phone']);
[, $me] = call('GET', '/auth/me', null, $tok);
check('3 devices (pc/tablet/phone) active together', count($me['devices']) === 3, $me['devices']);

$pc2 = uuid();
[, $pc2Login] = call('POST', '/auth/dev-login', ['email' => 'kim@test.kr', 'deviceId' => $pc2, 'deviceType' => 'pc']);
check('second pc replaces first', $pc2Login['replacedDevices'] === [$pc1], $pc2Login);
[$s, $b] = call('GET', '/auth/me', null, $tok);
check('replaced pc gets device_replaced', $s === 401 && $b['code'] === 'device_replaced', $b);
[$s] = call('GET', '/auth/me', null, $tabLogin['accessToken']);
check('tablet unaffected', $s === 200);

[$s, $r1] = call('POST', '/auth/refresh', ['refreshToken' => $pc2Login['refreshToken']]);
check('refresh rotates', $s === 200 && $r1['refreshToken'] !== $pc2Login['refreshToken'], $r1);
[$s, $b] = call('POST', '/auth/refresh', ['refreshToken' => $pc2Login['refreshToken']]);
check('reused refresh token → 401 refresh_invalid', $s === 401 && $b['code'] === 'refresh_invalid', $b);
[$s] = call('POST', '/auth/refresh', ['refreshToken' => $r1['refreshToken']]);
check('reuse revokes device session', $s === 401);

[, $L] = call('POST', '/auth/dev-login', ['email' => 'kim@test.kr', 'deviceId' => $pc2, 'deviceType' => 'pc']);
$tok = $L['accessToken'];

echo "g5 sso\n";
$g5Member = null;
Config::load($cfg + ['g5_common' => __FILE__, 'g5_member_resolver' => function () use (&$g5Member) { return $g5Member; }]);
[, $b] = call('GET', '/auth/providers');
check('g5 provider enabled', $b['g5'] === true, $b);
[$s, , $h] = call('GET', '/auth/g5/start?target=web');
check('not logged in → gnuboard login with return url', $s === 302 && str_starts_with($h['Location'], '/bbs/login.php?url=')
    && str_contains(urldecode($h['Location']), 'http://api.test/auth/g5/start?target=web'), $h);
$g5Member = ['mb_id' => 'hong', 'mb_email' => 'hong@xam.kr', 'mb_nick' => '홍길동'];
[$s, , $h] = call('GET', '/auth/g5/start?target=web');
check('logged in → web callback with code', $s === 302 && str_starts_with($h['Location'], 'http://web.test/auth/callback?code='), $h);
parse_str((string) parse_url($h['Location'], PHP_URL_QUERY), $qq);
[$s, $b] = call('POST', '/auth/exchange', ['code' => $qq['code'], 'deviceId' => uuid(), 'deviceType' => 'phone']);
check('exchange g5 code', $s === 200 && isset($b['accessToken']), $b);
[, $me] = call('GET', '/auth/me', null, $b['accessToken']);
check('g5 member mapped', $me['user']['email'] === 'hong@xam.kr' && $me['user']['provider'] === 'g5' && $me['user']['name'] === '홍길동', $me);
[$s] = call('POST', '/auth/exchange', ['code' => $qq['code'], 'deviceId' => uuid(), 'deviceType' => 'phone']);
check('login code is single-use', $s === 401);
$res = Hsb\handle(new Request('GET', '/auth/g5/start', ['target' => 'app'], [], ''));
check('app target → deep-link bridge page', $res->status === 200 && str_contains($res->body, 'haeseolbook://auth/callback?code='));
Config::load($cfg);

echo "catalog\n";
[$s, $books] = call('GET', '/books');
check('books (anonymous)', $s === 200 && count($books) === 1 && $books[0]['owned'] === null && $books[0]['videoCount'] === 8, $books);
[$s] = call('GET', '/books/sample-electric/manifest');
check('manifest requires login', $s === 401);
[$s, $m] = call('GET', '/books/sample-electric/manifest', null, $tok);
check('manifest', $s === 200 && count($m['pages']) === 2 && count($m['quizzes']) === 8 && count($m['regions']) === 8, $s);
check('manifest video segments + cues', count($m['videoSegments']) === 8 && count($m['videoSegments'][0]['cues']) === 4);
check('manifest solutions', count($m['solutions']) === 8 && str_contains($m['solutions'][0]['markdown'], '정답'));
[, $books] = call('GET', '/books', null, $tok);
check('opened book is in library', $books[0]['owned'] === true);
[$s] = call('GET', '/books/nope/manifest', null, $tok);
check('unknown book → 404', $s === 404);

echo "assets\n";
$url = $m['imageUrls']['sample-electric-p1']['sm'];
$path = substr($url, strlen('http://api.test'));
[$s, $file] = call('GET', $path);
check('signed image served', $s === 200 && is_string($file) && is_file($file), [$s, $file]);
[$s] = call('GET', preg_replace('/sig=[^&]+/', 'sig=AAAA', $path));
check('tampered signature → 403', $s === 403);
[$s] = call('GET', str_replace('/sm/1.webp', '/hi/1.webp', $path));
check('signature bound to key → 403', $s === 403);
[$s] = call('GET', preg_replace('/u=[^&]+/', 'u=other', $path));
check('signature bound to user → 403', $s === 403);

echo "ink\n";
$stroke = fn (string $id, int $t) => ['id' => $id, 'tool' => 'pen', 'color' => '#1d4ed8', 'size' => 0.003, 'points' => [[0.1, 0.2, 0.5], [0.2, 0.25, 0.6]], 'videoTime' => 12.5, 'createdAt' => $t];
$ink = fn (array $strokes) => ['version' => 1, 'pageId' => 'sample-electric-p1', 'strokes' => $strokes];
$push = fn (int $base, array $strokes, string $sum, string $t) => call('PUT', '/ink', [
    'bookId' => 'sample-electric', 'pageId' => 'sample-electric-p1', 'baseRev' => $base, 'ink' => $ink($strokes), 'checksum' => $sum, 'deviceId' => 'ignored',
], $t);
[$s, $b] = $push(0, [$stroke('a', 1)], str_repeat('1', 16), $tok);
check('first push → rev 1', $s === 200 && $b === ['status' => 'ok', 'rev' => 1, 'checksum' => str_repeat('1', 16)], $b);
[$s, $b] = $push(0, [$stroke('b', 2)], str_repeat('2', 16), $tabLogin['accessToken']);
check('stale baseRev from tablet → conflict with server copy', $s === 200 && $b['status'] === 'conflict' && $b['server']['rev'] === 1 && $b['server']['ink']['strokes'][0]['id'] === 'a', $b);
[$s, $b] = $push(1, [$stroke('a', 1), $stroke('b', 2)], str_repeat('3', 16), $tabLogin['accessToken']);
check('merged push → rev 2', $b['status'] === 'ok' && $b['rev'] === 2, $b);
[$s, $b] = $push(1, [$stroke('a', 1), $stroke('b', 2)], str_repeat('3', 16), $tok);
check('same content, stale rev → idempotent ok', $b === ['status' => 'ok', 'rev' => 2, 'checksum' => str_repeat('3', 16)], $b);
[$s, $list] = call('GET', '/ink/sample-electric', null, $tok);
check('list ink (other device sees merge)', $s === 200 && count($list) === 1 && count($list[0]['ink']['strokes']) === 2 && $list[0]['ink']['strokes'][0]['videoTime'] === 12.5, $list);
[$s, $list] = call('GET', '/ink/sample-electric?updatedAfter=' . urlencode(gmdate('c', time() + 60)), null, $tok);
check('incremental list (none newer)', $s === 200 && $list === [], $list);
[$s] = call('PUT', '/ink', ['bookId' => 'sample-electric', 'pageId' => 'sample-electric-p1', 'baseRev' => 2, 'checksum' => str_repeat('4', 16), 'ink' => $ink([['id' => 'x', 'tool' => 'laser']])], $tok);
check('invalid stroke → 400', $s === 400);
[$s] = call('PUT', '/ink', ['bookId' => 'sample-electric', 'pageId' => 'other-p1', 'baseRev' => 0, 'checksum' => str_repeat('4', 16), 'ink' => ['version' => 1, 'pageId' => 'other-p1', 'strokes' => []]], $tok);
check('page from another book → 404', $s === 404);

echo "study\n";
[$s, $b] = call('POST', '/books/sample-electric/attempts', ['quizId' => 'sample-electric-q1', 'chosen' => 1], $tok);
check('wrong answer', $s === 200 && $b === ['correct' => false, 'answer' => 2], $b);
call('POST', '/books/sample-electric/attempts', ['quizId' => 'sample-electric-q1', 'chosen' => 2], $tok);
[$s, $b] = call('POST', '/books/sample-electric/attempts', ['quizId' => 'sample-electric-q3', 'chosen' => 3], $tok);
check('right answer', $b['correct'] === true);
[$s, $b] = call('GET', '/books/sample-electric/attempts', null, $tok);
$q1 = array_values(array_filter($b, fn ($a) => $a['quizId'] === 'sample-electric-q1'))[0] ?? null;
check('wrong-note keeps everWrong after retry', $q1 && $q1['correct'] === true && $q1['everWrong'] === true && $q1['tries'] === 2, $b);
[$s] = call('POST', '/books/sample-electric/attempts', ['quizId' => 'sample-electric-q1', 'chosen' => 9], $tok);
check('out-of-range choice → 400', $s === 400);

echo "admin / ip-hub package\n";
[$s] = call('GET', '/admin/books');
check('admin without token → 401', $s === 401);
$adm = ['X-Admin-Token' => str_repeat('t', 40)];
[$s, $b] = call('GET', '/admin/books', null, null, $adm);
check('admin books with version', $s === 200 && $b[0]['version'] === '1.0.0' && $b[0]['readers'] === 1 && $b[0]['published'] === true, $b);

/** 원본 패키지를 복사해 변형한 zip 을 만든다 */
$mutate = function (callable $fn) use ($pkg, $tmp): string {
    $copy = "{$tmp}/m-" . bin2hex(random_bytes(3)) . '.zip';
    copy($pkg, $copy);
    $z = new ZipArchive();
    $z->open($copy);
    $fn($z);
    $z->close();
    return $copy;
};
$expectFail = function (string $zip, string $needle) {
    try { Hsb\Import\import_package($zip); return 'no error'; }
    catch (Hsb\HttpError $e) { return str_contains($e->getMessage(), $needle) ? true : $e->getMessage(); }
};
$r = $expectFail($mutate(fn ($z) => $z->addFromString('quizzes.json', '[]')), '해시 불일치');
check('tampered file rejected', $r === true, $r);
$r = $expectFail($mutate(fn ($z) => $z->addFromString('../../evil.php', '<?php')), '파일 목록');
check('extra/traversal entry rejected', $r === true, $r);
$r = $expectFail($mutate(function ($z) {
    $item = json_decode($z->getFromName('item.json'), true);
    $item['files']['../evil.json'] = hash('sha256', 'x');
    $z->addFromString('item.json', json_encode($item));
    $z->addFromString('../evil.json', 'x');
}), '허용되지 않은 파일 경로');
check('declared traversal path rejected', $r === true, $r);
$r = $expectFail($mutate(function ($z) {
    $item = json_decode($z->getFromName('item.json'), true);
    $item['type'] = 'game';
    $z->addFromString('item.json', json_encode($item));
}), 'ebook-video');
check('other item type (e.g. game) rejected', $r === true, $r);
check('re-import same package is idempotent', Hsb\Import\import_package($pkg)['quizzes'] === 8);
[, $list] = call('GET', '/ink/sample-electric', null, $tok);
check('user ink survives re-import', count($list) === 1 && count($list[0]['ink']['strokes']) === 2);

[$s] = call('POST', '/admin/books/sample-electric/publish', ['published' => false], null, $adm);
[, $books] = call('GET', '/books');
check('unpublish hides from catalog', $s === 200 && $books === [], $books);
[$s] = call('GET', '/books/sample-electric/manifest', null, $tok);
check('unpublished manifest → 404', $s === 404);
call('POST', '/admin/books/sample-electric/publish', ['published' => true], null, $adm);
[, $books] = call('GET', '/books');
check('republish', count($books) === 1);

echo "lan auto url\n";
Config::load(['public_api_url' => 'auto', 'web_url' => 'auto'] + $cfg);
$_SERVER['HTTP_HOST'] = '192.168.0.5:8080';
Hsb\Ctx::$base = '/api';
$signed = Hsb\Storage::sign('books/x/sm/1.webp', 'u1');
check('auto public url uses request host + /api', str_starts_with($signed, 'http://192.168.0.5:8080/api/assets/books/x/sm/1.webp?'), $signed);
check('auto web url = request origin', Hsb\web_url() === 'http://192.168.0.5:8080' && Hsb\web_origin() === 'http://192.168.0.5:8080');
$_SERVER['HTTP_HOST'] = 'evil.com/x?<script>';
check('host header sanitized', Hsb\Ctx::origin() === 'http://evil.comxscript');
unset($_SERVER['HTTP_HOST']);
Hsb\Ctx::$base = '';
Config::load($cfg);

echo "http\n";
[$s, , $h] = call('OPTIONS', '/ink', null, null, ['Origin' => 'http://web.test']);
check('CORS preflight for web origin', $s === 204 && ($h['Access-Control-Allow-Origin'] ?? '') === 'http://web.test', $h);
[, , $h] = call('GET', '/health', null, null, ['Origin' => 'https://evil.example']);
check('no CORS for unknown origin', !isset($h['Access-Control-Allow-Origin']));
[, , $h] = call('GET', '/health', null, null, ['Origin' => 'tauri://localhost']);
check('CORS for Tauri app', ($h['Access-Control-Allow-Origin'] ?? '') === 'tauri://localhost');
[$s] = call('GET', '/nope');
check('404', $s === 404);
[$s] = call('DELETE', '/books');
check('405', $s === 405);

echo "\n" . ($n - $fails) . "/{$n} passed\n";
exit($fails ? 1 : 0);
