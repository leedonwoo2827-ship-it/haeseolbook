<?php
declare(strict_types=1);

namespace Hsb;

/** HS256 JWT (외부 라이브러리 없이) */
final class Jwt
{
    public static function sign(array $claims, int $ttlSec, string $secret): string
    {
        $now = time();
        $claims += ['iat' => $now, 'exp' => $now + $ttlSec];
        $h = b64url(json_encode(['alg' => 'HS256', 'typ' => 'JWT']));
        $p = b64url(json_encode($claims, JSON_UNESCAPED_UNICODE));
        return "{$h}.{$p}." . b64url(hash_hmac('sha256', "{$h}.{$p}", $secret, true));
    }

    /** 서명·만료가 유효하면 claims, 아니면 null */
    public static function verify(string $token, string $secret, ?string $aud = null): ?array
    {
        $parts = explode('.', $token);
        if (count($parts) !== 3) return null;
        [$h, $p, $s] = $parts;
        $header = json_decode(b64url_decode($h), true);
        if (!is_array($header) || ($header['alg'] ?? '') !== 'HS256') return null;
        if (!hash_equals(b64url(hash_hmac('sha256', "{$h}.{$p}", $secret, true)), $s)) return null;
        $claims = json_decode(b64url_decode($p), true);
        if (!is_array($claims) || !isset($claims['exp']) || $claims['exp'] < time()) return null;
        if ($aud !== null && ($claims['aud'] ?? null) !== $aud) return null;
        if ($aud === null && isset($claims['aud'])) return null;
        return $claims;
    }
}
