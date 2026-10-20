<?php
declare(strict_types=1);

/**
 * IP 허브 아이템 패키지(.hsbpkg.zip) 가져오기.
 * item.json 의 파일 목록·sha256 과 실제 zip 항목이 정확히 일치할 때만 적재한다(경로 조작·변조 차단).
 */

namespace Hsb\Import;

use Hsb\Db;
use Hsb\HttpError;

use function Hsb\Seed\seed;

const MAX_FILES = 3000;
const MAX_UNCOMPRESSED = 300 * 1024 * 1024;

function import_package(string $zipPath): array
{
    if (!class_exists(\ZipArchive::class)) throw new HttpError(500, '서버에 PHP zip 확장이 필요합니다');
    $zip = new \ZipArchive();
    if ($zip->open($zipPath) !== true) throw new HttpError(400, 'zip 파일을 열 수 없습니다');
    $tmp = sys_get_temp_dir() . '/hsbpkg-' . bin2hex(random_bytes(6));
    try {
        $item = json_decode((string) $zip->getFromName('item.json'), true);
        if (!is_array($item) || ($item['schema'] ?? '') !== 'ipitem/1' || ($item['type'] ?? '') !== 'ebook-video') {
            throw new HttpError(400, 'item.json 이 없거나 해설북 패키지(ebook-video)가 아닙니다');
        }
        if (!preg_match('/^[a-z0-9-]{1,60}$/', (string) ($item['id'] ?? ''))) throw new HttpError(400, 'item.id 형식 오류');
        if (!preg_match('/^\d+\.\d+\.\d+$/', (string) ($item['version'] ?? ''))) throw new HttpError(400, 'item.version 은 x.y.z 형식이어야 합니다');
        $files = $item['files'] ?? null;
        if (!is_array($files) || !$files || count($files) > MAX_FILES) throw new HttpError(400, 'item.files 가 올바르지 않습니다');

        $entries = [];
        $total = 0;
        for ($i = 0; $i < $zip->numFiles; $i++) {
            $st = $zip->statIndex($i);
            $name = $st['name'];
            if (str_ends_with($name, '/')) continue;
            $total += $st['size'];
            $entries[$name] = $i;
        }
        if ($total > MAX_UNCOMPRESSED) throw new HttpError(413, '패키지 압축 해제 크기가 너무 큽니다');
        unset($entries['item.json']);
        $expected = array_keys($files);
        sort($expected);
        $actual = array_keys($entries);
        sort($actual);
        if ($expected !== $actual) throw new HttpError(400, 'zip 구성이 item.json 의 파일 목록과 다릅니다');

        foreach ($files as $name => $hash) {
            // 허용 경로: 루트 JSON 또는 pages/{xs,sm,hi}/<n>.webp
            if (!preg_match('#^([a-z_]+\.json|pages/(xs|sm|hi)/\d{1,4}\.webp)$#', $name)) throw new HttpError(400, "허용되지 않은 파일 경로: {$name}");
            $data = $zip->getFromIndex($entries[$name]);
            if ($data === false || !hash_equals((string) $hash, hash('sha256', $data))) throw new HttpError(400, "파일 해시 불일치: {$name}");
            $dest = "{$tmp}/{$name}";
            @mkdir(dirname($dest), 0775, true);
            file_put_contents($dest, $data);
        }
        $book = json_decode((string) file_get_contents("{$tmp}/book.json"), true);
        if (($book['id'] ?? null) !== $item['id']) throw new HttpError(400, 'book.json 의 id 가 item.id 와 다릅니다');

        try {
            $result = seed($tmp);
        } catch (\Hsb\Seed\SeedError $e) {
            throw new HttpError(400, '교재 데이터 오류: ' . $e->getMessage());
        }
        Db::exec('UPDATE hsb_books SET item_version = ? WHERE id = ?', [$item['version'], $item['id']]);
        return $result + ['version' => $item['version']];
    } finally {
        $zip->close();
        rrmdir($tmp);
    }
}

function rrmdir(string $dir): void
{
    if (!is_dir($dir)) return;
    $it = new \RecursiveIteratorIterator(new \RecursiveDirectoryIterator($dir, \FilesystemIterator::SKIP_DOTS), \RecursiveIteratorIterator::CHILD_FIRST);
    foreach ($it as $f) $f->isDir() ? rmdir($f->getPathname()) : unlink($f->getPathname());
    rmdir($dir);
}
