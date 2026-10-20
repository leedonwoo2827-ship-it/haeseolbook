<?php
declare(strict_types=1);

namespace Hsb;

use PDO;

/** 설정·DB·HTTP 공통 유틸. 프레임워크 없이 PHP 8.1+ 와 PDO 만 쓴다(일반 리눅스 호스팅 FTP 배포 가능). */

final class Config
{
    private static ?array $c = null;

    public static function load(array $override = []): void
    {
        // HSB_CONFIG 로 다른 설정 파일을 고를 수 있다 (사내 랜 공유: server/config.lan.php)
        $file = getenv('HSB_CONFIG') ?: dirname(__DIR__) . '/config.php';
        $base = is_file($file) ? require $file : [];
        self::$c = array_replace($base, $override);
    }

    public static function get(string $key, mixed $default = null): mixed
    {
        if (self::$c === null) self::load();
        return self::$c[$key] ?? $default;
    }

    public static function must(string $key): string
    {
        $v = (string) self::get($key, '');
        if ($v === '') throw new \RuntimeException("config.php 의 {$key} 값이 필요합니다");
        return $v;
    }

    /**
     * 이 API 의 공개 주소. config 'public_api_url' 이 'auto' 면 요청 Host + 기준 경로로 계산한다
     * (사내 랜 공유: 랜 IP 가 바뀌어도 서명 URL·리다이렉트가 맞게).
     */
    public static function apiUrl(): string
    {
        $v = (string) self::get('public_api_url', 'auto');
        return rtrim($v === 'auto' || $v === '' ? Ctx::origin() . Ctx::$base : $v, '/');
    }

    /** @return array{client_id:string,client_secret:string}|null */
    public static function oauth(string $provider): ?array
    {
        $o = self::get($provider);
        return is_array($o) && !empty($o['client_id']) ? $o : null;
    }
}

/** 현재 요청의 출처·기준 경로 ('auto' 주소 계산용) */
final class Ctx
{
    public static string $base = '';

    public static function origin(): string
    {
        $https = (!empty($_SERVER['HTTPS']) && $_SERVER['HTTPS'] !== 'off') || ($_SERVER['HTTP_X_FORWARDED_PROTO'] ?? '') === 'https';
        $host = (string) ($_SERVER['HTTP_HOST'] ?? 'localhost');
        return ($https ? 'https' : 'http') . '://' . preg_replace('/[^A-Za-z0-9.:\[\]-]/', '', $host);
    }
}

final class Db
{
    private static ?PDO $pdo = null;

    public static function pdo(): PDO
    {
        if (self::$pdo === null) {
            $dsn = Config::must('db_dsn');
            $opts = [PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION, PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC];
            if (str_starts_with($dsn, 'mysql:')) {
                // UPDATE 의 rowCount 를 "변경된 행"이 아니라 "일치한 행"으로 받는다 (낙관적 잠금 판정용)
                $opts[PDO::MYSQL_ATTR_FOUND_ROWS] = true;
                $opts[PDO::ATTR_EMULATE_PREPARES] = false;
            }
            self::$pdo = new PDO($dsn, (string) Config::get('db_user', ''), (string) Config::get('db_pass', ''), $opts);
            if (self::isSqlite()) self::$pdo->exec('PRAGMA foreign_keys = ON');
            else self::$pdo->exec("SET time_zone = '+00:00'");
        }
        return self::$pdo;
    }

    public static function reset(): void { self::$pdo = null; }

    public static function isSqlite(): bool { return str_starts_with(Config::must('db_dsn'), 'sqlite:'); }

    public static function all(string $sql, array $p = []): array
    {
        $st = self::pdo()->prepare($sql);
        $st->execute($p);
        return $st->fetchAll();
    }

    public static function one(string $sql, array $p = []): ?array
    {
        $st = self::pdo()->prepare($sql);
        $st->execute($p);
        $r = $st->fetch();
        return $r === false ? null : $r;
    }

    /** @return int 영향받은(일치한) 행 수 */
    public static function exec(string $sql, array $p = []): int
    {
        $st = self::pdo()->prepare($sql);
        $st->execute($p);
        return $st->rowCount();
    }

    public static function insert(string $table, array $row): void
    {
        $cols = array_keys($row);
        self::exec(
            "INSERT INTO {$table} (" . implode(',', $cols) . ') VALUES (' . implode(',', array_fill(0, count($cols), '?')) . ')',
            array_values($row)
        );
    }

    /** 키로 UPDATE 를 시도하고 없으면 INSERT (MySQL/SQLite 공용) */
    public static function upsert(string $table, array $keys, array $data): void
    {
        $set = implode(',', array_map(fn ($c) => "{$c}=?", array_keys($data)));
        $where = implode(' AND ', array_map(fn ($c) => "{$c}=?", array_keys($keys)));
        if ($data && self::exec("UPDATE {$table} SET {$set} WHERE {$where}", [...array_values($data), ...array_values($keys)]) > 0) return;
        if (!$data && self::one("SELECT 1 FROM {$table} WHERE {$where}", array_values($keys))) return;
        self::insert($table, $keys + $data);
    }

    public static function tx(callable $fn): mixed
    {
        $pdo = self::pdo();
        $pdo->beginTransaction();
        try {
            $r = $fn();
            $pdo->commit();
            return $r;
        } catch (\Throwable $e) {
            if ($pdo->inTransaction()) $pdo->rollBack();
            throw $e;
        }
    }

    /** MySQL 스키마를 SQLite 로 바꿔 실행 (로컬 테스트용) */
    public static function migrate(string $mysqlSchemaFile): void
    {
        $sql = file_get_contents($mysqlSchemaFile);
        $sql = preg_replace('/--[^\n]*\n/', "\n", $sql);
        if (self::isSqlite()) {
            $sql = preg_replace('/\)\s*ENGINE=[^;]*;/', ');', $sql);
            $sql = preg_replace('/BIGINT\s+NOT NULL AUTO_INCREMENT PRIMARY KEY/', 'INTEGER PRIMARY KEY AUTOINCREMENT', $sql);
            $sql = preg_replace('/,\s*KEY \w+ \([^)]*\)/', '', $sql);
            $sql = preg_replace('/UNIQUE KEY \w+ \(/', 'UNIQUE (', $sql);
        }
        foreach (array_filter(array_map('trim', explode(';', $sql))) as $stmt) self::pdo()->exec($stmt);
    }
}

final class HttpError extends \RuntimeException
{
    public function __construct(public readonly int $status, string $message, public readonly ?string $errorCode = null, public readonly array $extra = [])
    {
        parent::__construct($message);
    }
}

final class Request
{
    private ?array $json = null;

    public function __construct(
        public readonly string $method,
        public readonly string $path,
        public readonly array $query,
        public readonly array $headers,
        private readonly string $body,
    ) {}

    public static function fromGlobals(): self
    {
        $uri = parse_url($_SERVER['REQUEST_URI'] ?? '/', PHP_URL_PATH) ?: '/';
        // index.php 가 /api 같은 하위 경로에 있어도 동작하도록 스크립트 디렉터리를 뗀다
        // (PHP 내장 서버는 확장자가 있는 경로에서 SCRIPT_NAME 을 요청 경로로 채우므로 index.php 일 때만 신뢰)
        $script = str_replace('\\', '/', (string) ($_SERVER['SCRIPT_NAME'] ?? ''));
        $base = (string) Config::get('base_path', str_ends_with($script, '/index.php') ? rtrim(dirname($script), '/') : '');
        Ctx::$base = $base;
        if ($base !== '' && str_starts_with($uri, $base)) $uri = substr($uri, strlen($base));
        $uri = preg_replace('#^/index\.php#', '', $uri);
        $headers = [];
        foreach ($_SERVER as $k => $v) {
            if (str_starts_with($k, 'HTTP_')) $headers[strtolower(str_replace('_', '-', substr($k, 5)))] = $v;
        }
        if (isset($_SERVER['CONTENT_TYPE'])) $headers['content-type'] = $_SERVER['CONTENT_TYPE'];
        // 일부 호스팅(Apache+FastCGI)은 Authorization 을 REDIRECT_ 접두로 넘긴다
        $headers['authorization'] ??= $_SERVER['REDIRECT_HTTP_AUTHORIZATION'] ?? null;
        $body = (string) file_get_contents('php://input', false, null, 0, 6 * 1024 * 1024);
        return new self($_SERVER['REQUEST_METHOD'] ?? 'GET', $uri === '' ? '/' : $uri, $_GET, $headers, $body);
    }

    public function header(string $name): ?string { return $this->headers[strtolower($name)] ?? null; }

    public function json(): array
    {
        if ($this->json === null) {
            if (strlen($this->body) > 5 * 1024 * 1024) throw new HttpError(413, '요청이 너무 큽니다');
            $d = $this->body === '' ? [] : json_decode($this->body, true);
            if (!is_array($d)) throw new HttpError(400, 'JSON 본문이 올바르지 않습니다');
            $this->json = $d;
        }
        return $this->json;
    }

    public function q(string $k): ?string
    {
        $v = $this->query[$k] ?? null;
        return is_string($v) ? $v : null;
    }
}

final class Response
{
    public function __construct(public int $status = 200, public array $headers = [], public string $body = '', public ?string $file = null) {}

    public static function json(mixed $data, int $status = 200): self
    {
        return new self($status, ['Content-Type' => 'application/json; charset=utf-8'], json_encode($data, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_PRESERVE_ZERO_FRACTION));
    }

    public static function noContent(): self { return new self(204); }

    public static function redirect(string $url): self { return new self(302, ['Location' => $url]); }

    public static function html(string $html): self { return new self(200, ['Content-Type' => 'text/html; charset=utf-8'], $html); }

    public function send(): void
    {
        http_response_code($this->status);
        foreach ($this->headers as $k => $v) header("{$k}: {$v}");
        if ($this->file !== null) {
            header('Content-Length: ' . filesize($this->file));
            readfile($this->file);
            return;
        }
        echo $this->body;
    }
}

final class Router
{
    /** @var array<int, array{string,string,callable}> */
    private array $routes = [];

    public function add(string $method, string $pattern, callable $handler): void
    {
        $re = '#^' . preg_replace(['#\{(\w+)\*\}#', '#\{(\w+)\}#'], ['(?P<$1>.+)', '(?P<$1>[^/]+)'], $pattern) . '$#';
        $this->routes[] = [$method, $re, $handler];
    }

    public function dispatch(Request $req): Response
    {
        $allowed = false;
        foreach ($this->routes as [$m, $re, $h]) {
            if (!preg_match($re, $req->path, $mm)) continue;
            if ($m !== $req->method) { $allowed = true; continue; }
            $params = array_map('rawurldecode', array_filter($mm, 'is_string', ARRAY_FILTER_USE_KEY));
            return $h($req, $params);
        }
        throw new HttpError($allowed ? 405 : 404, $allowed ? '허용되지 않은 메서드입니다' : '없는 경로입니다');
    }
}

function now(int $offsetSec = 0): string
{
    return gmdate('Y-m-d H:i:s', time() + $offsetSec);
}

function new_id(): string
{
    return bin2hex(random_bytes(12));
}

function b64url(string $bin): string
{
    return rtrim(strtr(base64_encode($bin), '+/', '-_'), '=');
}

function b64url_decode(string $s): string
{
    return (string) base64_decode(strtr($s, '-_', '+/'), true);
}
