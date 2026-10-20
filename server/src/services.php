<?php
declare(strict_types=1);

namespace Hsb;

const ACCESS_TTL = 15 * 60;
const REFRESH_TTL_DAYS = 30;
const ASSET_TTL = 6 * 60 * 60;
const LOGIN_CODE_TTL = 5 * 60;
const DEVICE_TYPES = ['pc', 'tablet', 'phone'];

final class Auth
{
    /** Authorization 헤더 → [userId, deviceId]. 기기가 밀려났으면 device_replaced */
    public static function require(Request $req): array
    {
        $h = (string) $req->header('authorization');
        if (!str_starts_with($h, 'Bearer ')) throw new HttpError(401, '로그인이 필요합니다', 'login_required');
        $c = Jwt::verify(substr($h, 7), Config::must('jwt_secret'));
        if (!$c) throw new HttpError(401, '토큰이 만료되었거나 올바르지 않습니다', 'token_invalid');
        $d = Db::one('SELECT user_id, revoked_at FROM hsb_devices WHERE id = ?', [(string) ($c['did'] ?? '')]);
        if (!$d || $d['user_id'] !== $c['sub'] || $d['revoked_at'] !== null) {
            throw new HttpError(401, '다른 기기에서 로그인되어 로그아웃되었습니다', 'device_replaced');
        }
        return [(string) $c['sub'], (string) $c['did']];
    }

    public static function optionalUserId(Request $req): ?string
    {
        $h = (string) $req->header('authorization');
        if (!str_starts_with($h, 'Bearer ')) return null;
        $c = Jwt::verify(substr($h, 7), Config::must('jwt_secret'));
        return $c ? (string) $c['sub'] : null;
    }

    public static function upsertUser(string $email, string $provider, ?string $name): string
    {
        $email = strtolower(trim($email));
        $u = Db::one('SELECT id FROM hsb_users WHERE email = ?', [$email]);
        if ($u) {
            if ($name) Db::exec('UPDATE hsb_users SET name = ? WHERE id = ?', [$name, $u['id']]);
            return $u['id'];
        }
        $id = new_id();
        Db::insert('hsb_users', ['id' => $id, 'email' => $email, 'name' => $name, 'provider' => $provider, 'created_at' => now()]);
        return $id;
    }

    /** 요청 본문의 기기 정보 검증 */
    public static function deviceFrom(array $b): array
    {
        $id = (string) ($b['deviceId'] ?? '');
        $type = (string) ($b['deviceType'] ?? '');
        if (!preg_match('/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i', $id)) throw new HttpError(400, 'deviceId 가 올바르지 않습니다');
        if (!in_array($type, DEVICE_TYPES, true)) throw new HttpError(400, 'deviceType 이 올바르지 않습니다');
        $label = isset($b['label']) ? mb_substr((string) $b['label'], 0, 80) : null;
        return ['id' => strtolower($id), 'type' => $type, 'label' => $label];
    }

    /**
     * 기기 등록 + 토큰 발급.
     * 정책: 기기 유형(pc/tablet/phone)마다 활성 기기 1대 → 같은 유형의 다른 기기는 revoke (Solve 정책 차용)
     */
    public static function issueForDevice(string $userId, array $device): array
    {
        $secret = b64url(random_bytes(32));
        $replaced = Db::tx(function () use ($userId, $device, $secret) {
            $existing = Db::one('SELECT user_id FROM hsb_devices WHERE id = ?', [$device['id']]);
            if ($existing && $existing['user_id'] !== $userId) throw new HttpError(400, '기기 식별자가 다른 계정에 등록되어 있습니다');
            $others = array_column(Db::all(
                'SELECT id FROM hsb_devices WHERE user_id = ? AND type = ? AND revoked_at IS NULL AND id <> ?',
                [$userId, $device['type'], $device['id']]
            ), 'id');
            foreach ($others as $o) Db::exec('UPDATE hsb_devices SET revoked_at = ?, refresh_hash = NULL WHERE id = ?', [now(), $o]);
            $row = [
                'user_id' => $userId, 'type' => $device['type'], 'label' => $device['label'],
                'refresh_hash' => hash('sha256', $secret), 'revoked_at' => null, 'last_seen_at' => now(),
            ];
            if ($existing) Db::upsert('hsb_devices', ['id' => $device['id']], $row);
            else Db::insert('hsb_devices', ['id' => $device['id']] + $row + ['created_at' => now()]);
            return $others;
        });
        return self::tokens($userId, $device['id'], $secret, $replaced);
    }

    public static function refresh(string $token): array
    {
        $dot = strpos($token, '.');
        if (!$dot) throw new HttpError(401, '잘못된 토큰입니다', 'refresh_invalid');
        $deviceId = substr($token, 0, $dot);
        $secret = substr($token, $dot + 1);
        $d = Db::one('SELECT * FROM hsb_devices WHERE id = ?', [$deviceId]);
        if (!$d || $d['revoked_at'] !== null) throw new HttpError(401, '다른 기기에서 로그인되어 로그아웃되었습니다', 'device_replaced');
        $tooOld = strtotime($d['last_seen_at'] . ' UTC') < time() - REFRESH_TTL_DAYS * 86400;
        if ($tooOld || !hash_equals((string) $d['refresh_hash'], hash('sha256', $secret))) {
            // 이미 회전된 토큰의 재사용 = 탈취 의심 → 기기 세션 종료
            Db::exec('UPDATE hsb_devices SET revoked_at = ?, refresh_hash = NULL WHERE id = ?', [now(), $deviceId]);
            throw new HttpError(401, '세션이 만료되었습니다. 다시 로그인해 주세요', 'refresh_invalid');
        }
        $next = b64url(random_bytes(32));
        $n = Db::exec('UPDATE hsb_devices SET refresh_hash = ?, last_seen_at = ? WHERE id = ? AND refresh_hash = ?', [hash('sha256', $next), now(), $deviceId, $d['refresh_hash']]);
        if ($n !== 1) throw new HttpError(409, '동시에 토큰 갱신이 요청되었습니다. 다시 시도해 주세요');
        return self::tokens($d['user_id'], $deviceId, $next, []);
    }

    public static function createLoginCode(string $userId): string
    {
        $code = b64url(random_bytes(24));
        Db::insert('hsb_login_codes', ['code' => $code, 'user_id' => $userId, 'expires_at' => now(LOGIN_CODE_TTL)]);
        return $code;
    }

    public static function exchangeLoginCode(string $code, array $device): array
    {
        $row = Db::one('SELECT * FROM hsb_login_codes WHERE code = ?', [$code]);
        if (!$row || $row['used_at'] !== null || $row['expires_at'] < now()) throw new HttpError(401, '로그인 코드가 만료되었습니다. 다시 로그인해 주세요');
        if (Db::exec('UPDATE hsb_login_codes SET used_at = ? WHERE code = ? AND used_at IS NULL', [now(), $code]) !== 1) {
            throw new HttpError(401, '이미 사용된 로그인 코드입니다');
        }
        return self::issueForDevice($row['user_id'], $device);
    }

    private static function tokens(string $userId, string $deviceId, string $secret, array $replaced): array
    {
        return [
            'accessToken' => Jwt::sign(['sub' => $userId, 'did' => $deviceId], ACCESS_TTL, Config::must('jwt_secret')),
            'refreshToken' => "{$deviceId}.{$secret}",
            'expiresIn' => ACCESS_TTL,
            'replacedDevices' => array_values($replaced),
        ];
    }
}

final class OAuth
{
    private static function callbackUrl(string $p): string
    {
        return Config::apiUrl() . "/auth/oauth/{$p}/callback";
    }

    public static function authorizeUrl(string $p, string $state): string
    {
        $c = Config::oauth($p) ?? throw new HttpError(400, "{$p} 로그인이 설정되지 않았습니다");
        if ($p === 'google') {
            return 'https://accounts.google.com/o/oauth2/v2/auth?' . http_build_query([
                'client_id' => $c['client_id'], 'redirect_uri' => self::callbackUrl($p), 'response_type' => 'code',
                'scope' => 'openid email profile', 'state' => $state, 'prompt' => 'select_account',
            ]);
        }
        return 'https://kauth.kakao.com/oauth/authorize?' . http_build_query([
            'client_id' => $c['client_id'], 'redirect_uri' => self::callbackUrl($p), 'response_type' => 'code',
            'scope' => 'account_email profile_nickname', 'state' => $state,
        ]);
    }

    /** @return array{email:string,name:?string} */
    public static function profile(string $p, string $code): array
    {
        $c = Config::oauth($p) ?? throw new HttpError(400, "{$p} 로그인이 설정되지 않았습니다");
        $tokenUrl = $p === 'google' ? 'https://oauth2.googleapis.com/token' : 'https://kauth.kakao.com/oauth/token';
        $tok = self::http('POST', $tokenUrl, http_build_query([
            'code' => $code, 'client_id' => $c['client_id'], 'client_secret' => $c['client_secret'],
            'redirect_uri' => self::callbackUrl($p), 'grant_type' => 'authorization_code',
        ]), ['Content-Type: application/x-www-form-urlencoded']);
        $access = (string) ($tok['access_token'] ?? '');
        if ($access === '') throw new HttpError(502, "{$p} 토큰 교환에 실패했습니다");
        if ($p === 'google') {
            $info = self::http('GET', 'https://openidconnect.googleapis.com/v1/userinfo', null, ["Authorization: Bearer {$access}"]);
            if (empty($info['email']) || ($info['email_verified'] ?? true) === false) throw new HttpError(400, '구글 계정 이메일을 확인할 수 없습니다');
            return ['email' => $info['email'], 'name' => $info['name'] ?? null];
        }
        $info = self::http('GET', 'https://kapi.kakao.com/v2/user/me', null, ["Authorization: Bearer {$access}"]);
        $acc = $info['kakao_account'] ?? [];
        if (empty($acc['email']) || ($acc['is_email_verified'] ?? true) === false) throw new HttpError(400, '카카오 계정 이메일 제공 동의가 필요합니다');
        return ['email' => $acc['email'], 'name' => $acc['profile']['nickname'] ?? null];
    }

    private static function http(string $method, string $url, ?string $body, array $headers): array
    {
        $ch = curl_init($url);
        curl_setopt_array($ch, [
            CURLOPT_CUSTOMREQUEST => $method, CURLOPT_RETURNTRANSFER => true, CURLOPT_TIMEOUT => 10,
            CURLOPT_HTTPHEADER => $headers, CURLOPT_POSTFIELDS => $body,
        ]);
        $res = curl_exec($ch);
        curl_close($ch);
        $d = is_string($res) ? json_decode($res, true) : null;
        return is_array($d) ? $d : [];
    }

    public static function bridgeHtml(string $deepLink): string
    {
        $attr = htmlspecialchars($deepLink, ENT_QUOTES);
        $js = json_encode($deepLink, JSON_HEX_TAG | JSON_HEX_AMP | JSON_UNESCAPED_SLASHES);
        return <<<HTML
<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>로그인 완료</title><style>
body{margin:0;min-height:100vh;display:grid;place-items:center;background:#f6f7f9;font-family:system-ui,-apple-system,'Apple SD Gothic Neo','Malgun Gothic',sans-serif;color:#111827}
.card{background:#fff;border:1px solid #e5e7eb;border-radius:16px;padding:32px 40px;max-width:420px;margin:16px;text-align:center;box-shadow:0 8px 24px rgba(0,0,0,.05)}
h1{font-size:20px;margin:0 0 8px}p{color:#4b5563;margin:0 0 20px;line-height:1.6}
a{display:inline-block;background:#111827;color:#fff;padding:12px 20px;border-radius:10px;text-decoration:none}
</style></head><body><div class="card"><h1>로그인이 완료되었어요</h1>
<p>해설북 앱으로 돌아가고 있습니다. 이 창이 자동으로 닫히지 않으면 닫아도 괜찮아요.</p>
<a href="{$attr}">앱으로 돌아가기</a></div><script>location.href={$js};</script></body></html>
HTML;
    }
}

/**
 * 페이지 이미지: 웹 루트 밖 디스크 + HMAC 서명 URL.
 * 서명에 사용자 id 를 넣어 URL 유출 시 추적 가능. 원본 PDF 는 서버에 두지 않는다.
 */
final class Storage
{
    public static function root(): string
    {
        return rtrim(str_replace('\\', '/', (string) realpath(Config::must('storage_dir')) ?: Config::must('storage_dir')), '/');
    }

    public static function sign(string $key, string $userId, int $ttl = ASSET_TTL): string
    {
        $exp = time() + $ttl;
        $q = http_build_query(['u' => $userId, 'exp' => $exp, 'sig' => self::mac($key, $exp, $userId)]);
        $path = implode('/', array_map('rawurlencode', explode('/', $key)));
        return Config::apiUrl() . "/assets/{$path}?{$q}";
    }

    public static function resolve(string $key, string $userId, int $exp, string $sig): ?string
    {
        if ($exp < time() || !hash_equals(self::mac($key, $exp, $userId), $sig)) return null;
        if (str_contains($key, '..') || str_contains($key, '\\')) return null;
        $file = self::root() . '/' . $key;
        return is_file($file) ? $file : null;
    }

    private static function mac(string $key, int $exp, string $userId): string
    {
        return b64url(hash_hmac('sha256', "{$key}\n{$exp}\n{$userId}", Config::must('asset_secret'), true));
    }
}

final class Catalog
{
    public static function list(?string $userId): array
    {
        $rows = Db::all(
            'SELECT b.*, (SELECT COUNT(*) FROM hsb_pages p WHERE p.book_id = b.id) AS page_count,
                    (SELECT COUNT(*) FROM hsb_quizzes q WHERE q.book_id = b.id) AS quiz_count,
                    (SELECT COUNT(*) FROM hsb_quizzes q WHERE q.book_id = b.id AND q.youtube_id IS NOT NULL) AS video_count,
                    (SELECT p.id FROM hsb_pages p WHERE p.book_id = b.id AND p.page_no = 1) AS cover_page_id,
                    (SELECT COUNT(*) FROM hsb_library l WHERE l.book_id = b.id AND l.user_id = ?) AS in_library
             FROM hsb_books b WHERE b.published_at IS NOT NULL ORDER BY b.year DESC, b.title',
            [$userId ?? '']
        );
        return array_map(fn ($b) => [
            'id' => $b['id'], 'title' => $b['title'], 'exam' => $b['exam'], 'subject' => $b['subject'],
            'year' => (int) $b['year'], 'round' => $b['round'], 'pageCount' => (int) $b['page_count'],
            'quizCount' => (int) $b['quiz_count'], 'videoCount' => (int) $b['video_count'], 'priceKrw' => 0,
            'coverPageId' => $b['cover_page_id'], 'owned' => $userId ? ((int) $b['in_library'] > 0) : null,
        ], $rows);
    }

    public static function requireBook(string $bookId): array
    {
        return Db::one('SELECT * FROM hsb_books WHERE id = ? AND published_at IS NOT NULL', [$bookId])
            ?? throw new HttpError(404, '교재를 찾을 수 없습니다');
    }

    /** 무료 교재: 내 서재에 담기 */
    public static function addToLibrary(string $userId, string $bookId): void
    {
        self::requireBook($bookId);
        if (!Db::one('SELECT 1 FROM hsb_library WHERE user_id = ? AND book_id = ?', [$userId, $bookId])) {
            Db::insert('hsb_library', ['user_id' => $userId, 'book_id' => $bookId, 'created_at' => now()]);
        }
    }

    public static function manifest(string $userId, string $bookId): array
    {
        // 무료 교재만 운영하므로 열람 시 자동으로 내 서재에 담는다
        self::addToLibrary($userId, $bookId);
        $summary = array_values(array_filter(self::list($userId), fn ($b) => $b['id'] === $bookId))[0];
        $pages = Db::all('SELECT * FROM hsb_pages WHERE book_id = ? ORDER BY page_no', [$bookId]);
        $regions = Db::all('SELECT r.* FROM hsb_regions r JOIN hsb_pages p ON p.id = r.page_id WHERE p.book_id = ? ORDER BY r.id', [$bookId]);
        $quizzes = Db::all('SELECT * FROM hsb_quizzes WHERE book_id = ? ORDER BY no', [$bookId]);

        $urls = [];
        foreach ($pages as $p) {
            $keys = json_decode($p['image_keys'], true);
            foreach (['xs', 'sm', 'hi'] as $s) $urls[$p['id']][$s] = Storage::sign($keys[$s], $userId);
        }
        return [
            'book' => $summary,
            'pages' => array_map(fn ($p) => ['id' => $p['id'], 'pageNo' => (int) $p['page_no'], 'width' => (float) $p['width'], 'height' => (float) $p['height']], $pages),
            'regions' => array_map(fn ($r) => [
                'id' => $r['id'], 'pageId' => $r['page_id'], 'kind' => $r['kind'], 'quizId' => $r['quiz_id'],
                'bbox' => ['x' => (float) $r['x'], 'y' => (float) $r['y'], 'w' => (float) $r['w'], 'h' => (float) $r['h']],
            ], $regions),
            'quizzes' => array_map(fn ($q) => [
                'id' => $q['id'], 'no' => (int) $q['no'], 'answer' => (int) $q['answer'],
                'choiceCount' => (int) $q['choice_count'], 'keywords' => json_decode($q['keywords'], true) ?: [],
            ], $quizzes),
            'solutions' => array_values(array_map(
                fn ($q) => ['quizId' => $q['id'], 'markdown' => $q['solution_md']],
                array_filter($quizzes, fn ($q) => $q['solution_md'] !== '')
            )),
            'videoSegments' => array_values(array_map(fn ($q) => [
                'quizId' => $q['id'], 'youtubeId' => $q['youtube_id'], 'startSec' => (float) $q['start_sec'],
                'endSec' => (float) $q['end_sec'], 'cues' => $q['cues'] ? json_decode($q['cues'], true) : [],
            ], array_filter($quizzes, fn ($q) => $q['youtube_id'] !== null && $q['start_sec'] !== null && $q['end_sec'] !== null))),
            'imageUrls' => (object) $urls,
            'urlExpiresAt' => gmdate('Y-m-d\TH:i:s\Z', time() + ASSET_TTL),
        ];
    }
}

final class Ink
{
    public static function list(string $userId, string $bookId, ?string $updatedAfter): array
    {
        Catalog::requireBook($bookId);
        $sql = 'SELECT page_id, rev, checksum, data, updated_at FROM hsb_ink_pages WHERE user_id = ? AND book_id = ?';
        $p = [$userId, $bookId];
        if ($updatedAfter !== null && ($ts = strtotime($updatedAfter)) !== false) {
            $sql .= ' AND updated_at > ?';
            $p[] = gmdate('Y-m-d H:i:s', $ts);
        }
        return array_map(fn ($r) => [
            'pageId' => $r['page_id'], 'rev' => (int) $r['rev'], 'checksum' => $r['checksum'],
            'ink' => json_decode($r['data'], true), 'updatedAt' => str_replace(' ', 'T', $r['updated_at']) . 'Z',
        ], Db::all($sql, $p));
    }

    /**
     * 낙관적 동시성: 클라이언트 baseRev == 서버 rev 일 때만 덮어쓴다.
     * 다르면 서버본을 돌려주고 클라이언트가 mergeInk 후 새 baseRev 로 재시도한다.
     */
    public static function push(string $userId, string $deviceId, array $b): array
    {
        $bookId = (string) ($b['bookId'] ?? '');
        $pageId = (string) ($b['pageId'] ?? '');
        $baseRev = $b['baseRev'] ?? null;
        $checksum = (string) ($b['checksum'] ?? '');
        $ink = $b['ink'] ?? null;
        if (!is_int($baseRev) || $baseRev < 0 || !preg_match('/^[0-9a-f]{16}$/', $checksum)) throw new HttpError(400, 'baseRev/checksum 이 올바르지 않습니다');
        self::validateInk($ink, $pageId);
        Catalog::requireBook($bookId);
        $page = Db::one('SELECT book_id FROM hsb_pages WHERE id = ?', [$pageId]);
        if (!$page || $page['book_id'] !== $bookId) throw new HttpError(404, '페이지를 찾을 수 없습니다');

        return Db::tx(function () use ($userId, $deviceId, $bookId, $pageId, $baseRev, $checksum, $ink) {
            $cur = Db::one('SELECT rev, checksum, data FROM hsb_ink_pages WHERE user_id = ? AND page_id = ?', [$userId, $pageId]);
            $curRev = $cur ? (int) $cur['rev'] : 0;
            if ($curRev !== $baseRev) {
                if ($cur && $cur['checksum'] === $checksum) return ['status' => 'ok', 'rev' => $curRev, 'checksum' => $checksum];
                return ['status' => 'conflict', 'server' => $cur
                    ? ['rev' => $curRev, 'checksum' => $cur['checksum'], 'ink' => json_decode($cur['data'], true)]
                    : ['rev' => 0, 'checksum' => '', 'ink' => ['version' => 1, 'pageId' => $pageId, 'strokes' => []]]];
            }
            $data = json_encode($ink, JSON_UNESCAPED_UNICODE | JSON_PRESERVE_ZERO_FRACTION);
            if ($cur) {
                $n = Db::exec(
                    'UPDATE hsb_ink_pages SET rev = ?, checksum = ?, data = ?, device_id = ?, updated_at = ? WHERE user_id = ? AND page_id = ? AND rev = ?',
                    [$curRev + 1, $checksum, $data, $deviceId, now(), $userId, $pageId, $curRev]
                );
                if ($n !== 1) throw new HttpError(409, '동시에 저장 요청이 발생했습니다. 다시 시도해 주세요');
            } else {
                Db::insert('hsb_ink_pages', [
                    'user_id' => $userId, 'book_id' => $bookId, 'page_id' => $pageId, 'rev' => 1,
                    'checksum' => $checksum, 'data' => $data, 'device_id' => $deviceId, 'updated_at' => now(),
                ]);
            }
            return ['status' => 'ok', 'rev' => $curRev + 1, 'checksum' => $checksum];
        });
    }

    /** shared.InkPage 스키마와 같은 규칙으로 검증 */
    private static function validateInk(mixed $ink, string $pageId): void
    {
        $bad = fn (string $why) => new HttpError(400, "필기 데이터 형식 오류: {$why}");
        if (!is_array($ink) || ($ink['version'] ?? null) !== 1 || ($ink['pageId'] ?? null) !== $pageId) throw $bad('version/pageId');
        $strokes = $ink['strokes'] ?? null;
        if (!is_array($strokes) || !array_is_list($strokes) || count($strokes) > 5000) throw $bad('strokes');
        foreach ($strokes as $s) {
            if (!is_array($s)) throw $bad('stroke');
            if (!is_string($s['id'] ?? null) || $s['id'] === '' || strlen($s['id']) > 64) throw $bad('stroke.id');
            if (!in_array($s['tool'] ?? null, ['pen', 'highlighter'], true)) throw $bad('stroke.tool');
            if (!is_string($s['color'] ?? null) || !preg_match('/^#[0-9a-fA-F]{6}$/', $s['color'])) throw $bad('stroke.color');
            if (!is_numeric($s['size'] ?? null) || $s['size'] <= 0 || $s['size'] > 0.1) throw $bad('stroke.size');
            if (!is_int($s['createdAt'] ?? null)) throw $bad('stroke.createdAt');
            $vt = $s['videoTime'] ?? null;
            if ($vt !== null && (!is_numeric($vt) || $vt < 0)) throw $bad('stroke.videoTime');
            $pts = $s['points'] ?? null;
            if (!is_array($pts) || !$pts || count($pts) > 5000) throw $bad('stroke.points');
            foreach ($pts as $pt) {
                if (!is_array($pt) || count($pt) !== 3 || !is_numeric($pt[0]) || !is_numeric($pt[1]) || !is_numeric($pt[2])) throw $bad('point');
            }
        }
    }
}

final class Study
{
    public static function submit(string $userId, string $bookId, array $b): array
    {
        Catalog::requireBook($bookId);
        $quizId = (string) ($b['quizId'] ?? '');
        $chosen = $b['chosen'] ?? null;
        if (!is_int($chosen) || $chosen < 1 || $chosen > 5) throw new HttpError(400, 'chosen 이 올바르지 않습니다');
        $q = Db::one('SELECT id, answer FROM hsb_quizzes WHERE id = ? AND book_id = ?', [$quizId, $bookId]) ?? throw new HttpError(404, '문항을 찾을 수 없습니다');
        $correct = (int) $q['answer'] === $chosen;
        Db::insert('hsb_quiz_attempts', ['user_id' => $userId, 'quiz_id' => $quizId, 'chosen' => $chosen, 'correct' => $correct ? 1 : 0, 'created_at' => now()]);
        return ['correct' => $correct, 'answer' => (int) $q['answer']];
    }

    /** 문항별 최신 시도 + 한 번이라도 틀렸는지 (오답노트) */
    public static function latest(string $userId, string $bookId): array
    {
        $rows = Db::all(
            'SELECT a.quiz_id, a.chosen, a.correct, a.created_at FROM hsb_quiz_attempts a JOIN hsb_quizzes q ON q.id = a.quiz_id
             WHERE a.user_id = ? AND q.book_id = ? ORDER BY a.created_at DESC, a.id DESC',
            [$userId, $bookId]
        );
        $out = [];
        foreach ($rows as $r) {
            $id = $r['quiz_id'];
            if (!isset($out[$id])) {
                $out[$id] = ['quizId' => $id, 'chosen' => (int) $r['chosen'], 'correct' => (bool) $r['correct'], 'tries' => 1, 'everWrong' => !$r['correct']];
            } else {
                $out[$id]['tries']++;
                $out[$id]['everWrong'] = $out[$id]['everWrong'] || !$r['correct'];
            }
        }
        return array_values($out);
    }
}
