<?php
declare(strict_types=1);

namespace Hsb;

function build_router(): Router
{
    $r = new Router();

    $r->add('GET', '/health', fn () => Response::json(['ok' => true]));

    // ---------- 인증 ----------
    $r->add('GET', '/auth/providers', fn () => Response::json([
        'g5' => g5_common_path() !== null,
        'dev' => (bool) Config::get('allow_dev_login', false),
        'google' => Config::oauth('google') !== null,
        'kakao' => Config::oauth('kakao') !== null,
    ]));

    /** 개발·검수용 이메일 로그인 (운영 config 에서 allow_dev_login=false) */
    $r->add('POST', '/auth/dev-login', function (Request $req) {
        if (!Config::get('allow_dev_login', false)) throw new HttpError(403, '개발용 로그인이 비활성화되어 있습니다');
        $b = $req->json();
        $email = (string) ($b['email'] ?? '');
        if (!filter_var($email, FILTER_VALIDATE_EMAIL)) throw new HttpError(400, '이메일 형식이 올바르지 않습니다');
        $userId = Auth::upsertUser($email, 'dev', isset($b['name']) ? mb_substr((string) $b['name'], 0, 40) : null);
        return Response::json(Auth::issueForDevice($userId, Auth::deviceFrom($b)));
    });

    /** target=web → 웹 /auth/callback, target=app → 딥링크 브릿지 페이지 */
    $r->add('GET', '/auth/oauth/{provider}/start', function (Request $req, array $p) {
        $prov = oauth_provider($p['provider']);
        $state = Jwt::sign(['target' => $req->q('target') === 'app' ? 'app' : 'web', 'aud' => 'oauth-state'], 600, Config::must('jwt_secret'));
        return Response::redirect(OAuth::authorizeUrl($prov, $state));
    });

    $r->add('GET', '/auth/oauth/{provider}/callback', function (Request $req, array $p) {
        $prov = oauth_provider($p['provider']);
        $state = Jwt::verify((string) $req->q('state'), Config::must('jwt_secret'), 'oauth-state')
            ?? throw new HttpError(400, '로그인 요청이 만료되었습니다. 다시 시도해 주세요');
        $code = (string) $req->q('code');
        if ($code === '') throw new HttpError(400, '로그인이 취소되었습니다');
        $profile = OAuth::profile($prov, $code);
        $loginCode = rawurlencode(Auth::createLoginCode(Auth::upsertUser($profile['email'], $prov, $profile['name'])));
        if ($state['target'] === 'app') {
            return Response::html(OAuth::bridgeHtml(Config::get('app_scheme', 'haeseolbook') . "://auth/callback?code={$loginCode}"));
        }
        return Response::redirect(web_url() . "/auth/callback?code={$loginCode}");
    });

    /**
     * 그누보드(출판사 사이트) 회원 SSO. 같은 도메인의 그누보드 세션을 읽어 1회용 로그인 코드를 발급한다.
     * 로그인 안 돼 있으면 그누보드 로그인 화면으로 보냈다가 이 주소로 되돌아온다.
     */
    $r->add('GET', '/auth/g5/start', function (Request $req) {
        $common = g5_common_path() ?? throw new HttpError(400, '사이트 회원 로그인이 설정되지 않았습니다');
        $target = $req->q('target') === 'app' ? 'app' : 'web';
        $member = g5_member($common);
        if ($member === null) {
            $back = Config::apiUrl() . "/auth/g5/start?target={$target}";
            return Response::redirect(Config::get('g5_login_url', '/bbs/login.php') . '?url=' . rawurlencode($back));
        }
        $email = filter_var($member['mb_email'] ?? '', FILTER_VALIDATE_EMAIL) ?: "{$member['mb_id']}@members.local";
        $userId = Auth::upsertUser($email, 'g5', ($member['mb_nick'] ?? '') ?: null);
        $loginCode = rawurlencode(Auth::createLoginCode($userId));
        if ($target === 'app') {
            return Response::html(OAuth::bridgeHtml(Config::get('app_scheme', 'haeseolbook') . "://auth/callback?code={$loginCode}"));
        }
        return Response::redirect(web_url() . "/auth/callback?code={$loginCode}");
    });

    $r->add('POST', '/auth/exchange', function (Request $req) {
        $b = $req->json();
        return Response::json(Auth::exchangeLoginCode((string) ($b['code'] ?? ''), Auth::deviceFrom($b)));
    });

    $r->add('POST', '/auth/refresh', fn (Request $req) => Response::json(Auth::refresh((string) ($req->json()['refreshToken'] ?? ''))));

    $r->add('POST', '/auth/logout', function (Request $req) {
        [, $deviceId] = Auth::require($req);
        Db::exec('UPDATE hsb_devices SET refresh_hash = NULL, revoked_at = ? WHERE id = ?', [now(), $deviceId]);
        return Response::noContent();
    });

    $r->add('GET', '/auth/me', function (Request $req) {
        [$userId, $deviceId] = Auth::require($req);
        return Response::json([
            'user' => Db::one('SELECT id, email, name, provider FROM hsb_users WHERE id = ?', [$userId]),
            'deviceId' => $deviceId,
            'devices' => array_map(fn ($d) => ['id' => $d['id'], 'type' => $d['type'], 'label' => $d['label'], 'lastSeenAt' => $d['last_seen_at']],
                Db::all('SELECT id, type, label, last_seen_at FROM hsb_devices WHERE user_id = ? AND revoked_at IS NULL ORDER BY last_seen_at DESC', [$userId])),
        ]);
    });

    $r->add('DELETE', '/auth/devices/{id}', function (Request $req, array $p) {
        [$userId] = Auth::require($req);
        Db::exec('UPDATE hsb_devices SET revoked_at = ?, refresh_hash = NULL WHERE id = ? AND user_id = ?', [now(), $p['id'], $userId]);
        return Response::noContent();
    });

    // ---------- 교재 ----------
    $r->add('GET', '/books', fn (Request $req) => Response::json(Catalog::list(Auth::optionalUserId($req))));

    $r->add('POST', '/books/{id}/claim', function (Request $req, array $p) {
        [$userId] = Auth::require($req);
        Catalog::addToLibrary($userId, $p['id']);
        return Response::json(['ok' => true]);
    });

    $r->add('GET', '/books/{id}/manifest', function (Request $req, array $p) {
        [$userId] = Auth::require($req);
        return Response::json(Catalog::manifest($userId, $p['id']));
    });

    // ---------- 채점·오답노트 ----------
    $r->add('POST', '/books/{id}/attempts', function (Request $req, array $p) {
        [$userId] = Auth::require($req);
        return Response::json(Study::submit($userId, $p['id'], $req->json()));
    });

    $r->add('GET', '/books/{id}/attempts', function (Request $req, array $p) {
        [$userId] = Auth::require($req);
        return Response::json(Study::latest($userId, $p['id']));
    });

    // ---------- 필기 동기화 ----------
    $r->add('GET', '/ink/{bookId}', function (Request $req, array $p) {
        [$userId] = Auth::require($req);
        return Response::json(Ink::list($userId, $p['bookId'], $req->q('updatedAfter')));
    });

    $r->add('PUT', '/ink', function (Request $req) {
        [$userId, $deviceId] = Auth::require($req);
        return Response::json(Ink::push($userId, $deviceId, $req->json()));
    });

    // ---------- 관리자 (IP 허브 패키지 업로드·게시) ----------
    $r->add('GET', '/admin', fn () => Response::html(Admin::html()) );

    $r->add('GET', '/admin/books', function (Request $req) {
        Admin::require($req);
        return Response::json(Admin::books());
    });

    $r->add('POST', '/admin/import', function (Request $req) {
        Admin::require($req);
        $f = $_FILES['package'] ?? null;
        if (!is_array($f) || ($f['error'] ?? UPLOAD_ERR_NO_FILE) !== UPLOAD_ERR_OK) {
            $code = is_array($f) ? (int) $f['error'] : UPLOAD_ERR_NO_FILE;
            throw new HttpError(400, $code === UPLOAD_ERR_INI_SIZE || $code === UPLOAD_ERR_FORM_SIZE
                ? '파일이 서버 업로드 한도(upload_max_filesize)를 넘습니다' : '패키지 파일이 없습니다');
        }
        return Response::json(Import\import_package((string) $f['tmp_name']));
    });

    $r->add('POST', '/admin/books/{id}/publish', function (Request $req, array $p) {
        Admin::require($req);
        Admin::setPublished($p['id'], (bool) ($req->json()['published'] ?? false));
        return Response::json(['ok' => true]);
    });

    // ---------- 서명된 페이지 이미지 ----------
    $r->add('GET', '/assets/{key*}', function (Request $req, array $p) {
        $exp = (int) $req->q('exp');
        $file = Storage::resolve($p['key'], (string) $req->q('u'), $exp, (string) $req->q('sig'))
            ?? throw new HttpError(403, '만료되었거나 잘못된 링크입니다');
        return new Response(200, [
            'Content-Type' => 'image/webp',
            'Cache-Control' => 'private, max-age=' . max(0, $exp - time()),
            'Cross-Origin-Resource-Policy' => 'cross-origin',
        ], '', $file);
    });

    return $r;
}

function g5_common_path(): ?string
{
    $p = (string) Config::get('g5_common', '');
    return $p !== '' && is_file($p) ? $p : null;
}

/**
 * 그누보드 common.php 를 불러와 현재 로그인 회원을 돌려준다(비로그인 null).
 * common.php 는 세션 시작·전역 변수를 만들므로 이 엔드포인트에서만 부른다.
 * 테스트에서는 config 'g5_member_resolver' 로 대체할 수 있다.
 */
function g5_member(string $common): ?array
{
    $resolver = Config::get('g5_member_resolver');
    if (is_callable($resolver)) return $resolver();
    $member = (static function () use ($common) {
        ob_start();
        try {
            include_once $common;
        } finally {
            ob_end_clean();
        }
        return $GLOBALS['member'] ?? null;
    })();
    return is_array($member) && !empty($member['mb_id']) ? $member : null;
}

function oauth_provider(string $p): string
{
    if (!in_array($p, ['google', 'kakao'], true)) throw new HttpError(400, '지원하지 않는 로그인 방식입니다');
    if (Config::oauth($p) === null) throw new HttpError(400, "{$p} 로그인이 설정되지 않았습니다");
    return $p;
}

/** 웹(PWA) + 앱 래퍼 출처만 CORS 허용 */
function cors_headers(Request $req): array
{
    $origin = (string) $req->header('origin');
    $allowed = [web_origin(), 'tauri://localhost', 'http://tauri.localhost', 'capacitor://localhost', 'https://localhost', 'http://localhost'];
    foreach ((array) Config::get('extra_origins', []) as $o) $allowed[] = $o;
    if ($origin === '' || !in_array($origin, $allowed, true)) return [];
    return [
        'Access-Control-Allow-Origin' => $origin,
        'Vary' => 'Origin',
        'Access-Control-Allow-Methods' => 'GET, POST, PUT, DELETE, OPTIONS',
        'Access-Control-Allow-Headers' => 'Authorization, Content-Type, X-Admin-Token',
        'Access-Control-Max-Age' => '600',
    ];
}

function handle(Request $req): Response
{
    $cors = cors_headers($req);
    if ($req->method === 'OPTIONS') return new Response(204, $cors);
    try {
        $res = build_router()->dispatch($req);
    } catch (HttpError $e) {
        $res = Response::json(['message' => $e->getMessage(), 'code' => $e->errorCode] + $e->extra, $e->status);
    } catch (\Throwable $e) {
        error_log('[haeseolbook] ' . $e);
        $res = Response::json(['message' => '서버 오류가 발생했습니다'], 500);
    }
    $res->headers += $cors + ['X-Content-Type-Options' => 'nosniff'];
    return $res;
}

/** 웹(PWA) 주소 (경로 포함). OAuth·사이트 로그인 완료 후 /auth/callback 으로 보낸다 */
function web_url(): string
{
    $v = (string) (Config::get('web_url') ?: Config::get('web_origin', 'auto'));
    return rtrim($v === 'auto' ? Ctx::origin() : $v, '/');
}

/** CORS 출처 비교용: web_url 의 scheme://host[:port] */
function web_origin(): string
{
    $u = parse_url(web_url());
    if (!isset($u['scheme'], $u['host'])) return '';
    return "{$u['scheme']}://{$u['host']}" . (isset($u['port']) ? ":{$u['port']}" : '');
}
