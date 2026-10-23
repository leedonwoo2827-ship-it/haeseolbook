<?php
declare(strict_types=1);

/** 교재 적재 로직 (bin/hsb.php CLI 와 테스트에서 공용). 파일 형식은 bin/hsb.php 주석 참고 */

namespace Hsb\Seed;

use Hsb\Db;
use Hsb\Storage;

final class SeedError extends \RuntimeException {}

function fail(string $msg): never
{
    throw new SeedError($msg);
}

function read_json(string $dir, string $name, bool $optional = false): array
{
    $f = "{$dir}/{$name}";
    if (!is_file($f)) {
        if ($optional) return [];
        fail("{$f} 이 없습니다");
    }
    $d = json_decode((string) file_get_contents($f), true);
    if (!is_array($d)) fail("{$f} JSON 형식 오류");
    return $d;
}

function num01(mixed $v): bool { return is_numeric($v) && $v >= 0 && $v <= 1; }

function validate_bbox(mixed $b, string $where): array
{
    if (!is_array($b) || !num01($b['x'] ?? null) || !num01($b['y'] ?? null) || !num01($b['w'] ?? null) || !num01($b['h'] ?? null)) {
        fail("{$where}: bbox 는 0–1 정규화 좌표 {x,y,w,h} 여야 합니다");
    }
    return ['x' => (float) $b['x'], 'y' => (float) $b['y'], 'w' => (float) $b['w'], 'h' => (float) $b['h']];
}

function validate_video_map(array $vm): array
{
    $out = [];
    foreach ($vm as $i => $v) {
        $w = "video_map[{$i}]";
        if (!is_int($v['no'] ?? null)) fail("{$w}: no 가 필요합니다");
        if (!preg_match('/^[\w-]{11}$/', (string) ($v['youtubeId'] ?? ''))) fail("{$w}: youtubeId(11자) 가 올바르지 않습니다");
        if (!is_numeric($v['startSec'] ?? null) || !is_numeric($v['endSec'] ?? null) || $v['endSec'] <= $v['startSec']) fail("{$w}: startSec < endSec 이어야 합니다");
        $cues = [];
        foreach ($v['cues'] ?? [] as $j => $c) {
            if (!is_numeric($c['t'] ?? null) || !is_int($c['pageNo'] ?? null) || !num01($c['x'] ?? null) || !num01($c['y'] ?? null)) fail("{$w}.cues[{$j}] 형식 오류");
            $cues[] = ['t' => (float) $c['t'], 'pageNo' => $c['pageNo'], 'x' => (float) $c['x'], 'y' => (float) $c['y']];
        }
        usort($cues, fn ($a, $b) => $a['t'] <=> $b['t']);
        $out[$v['no']] = [
            'youtubeId' => $v['youtubeId'], 'startSec' => (float) $v['startSec'], 'endSec' => (float) $v['endSec'], 'cues' => $cues,
            'pageNo' => isset($v['pageNo']) ? (int) $v['pageNo'] : null,
            'bbox' => isset($v['bbox']) ? validate_bbox($v['bbox'], $w) : null,
        ];
    }
    return $out;
}

function apply_videos(string $bookId, array $videos): void
{
    foreach ($videos as $no => $v) {
        $n = Db::exec(
            'UPDATE hsb_quizzes SET youtube_id = ?, start_sec = ?, end_sec = ?, cues = ? WHERE book_id = ? AND no = ?',
            [$v['youtubeId'], $v['startSec'], $v['endSec'], $v['cues'] ? json_encode($v['cues']) : null, $bookId, $no]
        );
        if ($n === 0) fail("video_map: {$no}번 문항이 교재에 없습니다");
        if ($v['bbox'] && $v['pageNo']) {
            $quizId = "{$bookId}-q{$no}";
            Db::exec("DELETE FROM hsb_regions WHERE quiz_id = ? AND kind = 'quiz'", [$quizId]);
            Db::insert('hsb_regions', [
                'id' => "{$bookId}-rv{$no}", 'page_id' => "{$bookId}-p{$v['pageNo']}", 'kind' => 'quiz', 'quiz_id' => $quizId,
            ] + $v['bbox']);
        }
    }
}

function seed(string $dir): array
{
    $dir = rtrim(str_replace('\\', '/', $dir), '/');
    $book = read_json($dir, 'book.json');
    if (!preg_match('/^[a-z0-9-]{1,60}$/', (string) ($book['id'] ?? ''))) fail('book.id 는 영소문자/숫자/하이픈이어야 합니다');
    foreach (['title', 'exam', 'subject', 'round'] as $k) if (!is_string($book[$k] ?? null)) fail("book.{$k} 가 필요합니다");
    $id = $book['id'];
    $pages = read_json($dir, 'pages.json');
    $regions = read_json($dir, 'regions.json', true);
    $quizzes = read_json($dir, 'quizzes.json', true);
    $solutions = array_column(read_json($dir, 'solutions.json', true), 'markdown', 'no');
    $videos = validate_video_map(read_json($dir, 'video_map.json', true));

    $root = Storage::root();
    foreach ($pages as $p) {
        foreach (['xs', 'sm', 'hi'] as $s) {
            $src = "{$dir}/{$p['files'][$s]}";
            if (!is_file($src)) fail("{$src} 이 없습니다");
            $dest = "{$root}/books/{$id}/{$s}/{$p['pageNo']}.webp";
            @mkdir(dirname($dest), 0775, true);
            copy($src, $dest) || fail("{$dest} 복사 실패");
        }
    }

    Db::tx(function () use ($id, $book, $pages, $regions, $quizzes, $solutions, $videos) {
        $now = \Hsb\now();
        $row = [
            'title' => $book['title'], 'exam' => $book['exam'], 'subject' => $book['subject'],
            'year' => (int) $book['year'], 'round' => $book['round'], 'published_at' => $now,
        ];
        if (Db::one('SELECT 1 FROM hsb_books WHERE id = ?', [$id])) Db::upsert('hsb_books', ['id' => $id], $row);
        else Db::insert('hsb_books', ['id' => $id] + $row + ['created_at' => $now]);
        // 페이지/문항 id 는 결정적(<bookId>-p<n>, -q<n>)이라 재적재해도 사용자 필기·채점 기록이 유지된다
        Db::exec('DELETE FROM hsb_regions WHERE page_id IN (SELECT id FROM hsb_pages WHERE book_id = ?)', [$id]);
        foreach ($pages as $p) {
            $keys = json_encode(['xs' => "books/{$id}/xs/{$p['pageNo']}.webp", 'sm' => "books/{$id}/sm/{$p['pageNo']}.webp", 'hi' => "books/{$id}/hi/{$p['pageNo']}.webp"]);
            Db::upsert('hsb_pages', ['id' => "{$id}-p{$p['pageNo']}"], [
                'book_id' => $id, 'page_no' => (int) $p['pageNo'], 'width' => (float) $p['width'], 'height' => (float) $p['height'], 'image_keys' => $keys,
            ]);
        }
        foreach ($quizzes as $q) {
            if (!is_int($q['no'] ?? null) || !is_int($q['answer'] ?? null)) fail('quizzes.json: no/answer 는 정수여야 합니다');
            Db::upsert('hsb_quizzes', ['id' => "{$id}-q{$q['no']}"], [
                'book_id' => $id, 'no' => $q['no'], 'answer' => $q['answer'], 'choice_count' => (int) ($q['choiceCount'] ?? 4),
                'keywords' => json_encode($q['keywords'] ?? [], JSON_UNESCAPED_UNICODE), 'solution_md' => (string) ($solutions[$q['no']] ?? ''),
            ]);
        }
        foreach ($regions as $i => $r) {
            $bbox = validate_bbox($r['bbox'] ?? null, "regions[{$i}]");
            Db::insert('hsb_regions', [
                'id' => "{$id}-r" . ($i + 1), 'page_id' => "{$id}-p{$r['pageNo']}", 'kind' => $r['kind'] === 'solution' ? 'solution' : 'quiz',
                'quiz_id' => isset($r['quizNo']) ? "{$id}-q{$r['quizNo']}" : null,
            ] + $bbox);
        }
        // 영상 연결은 패키지가 정본 — 이번 패키지에 없는 예전 영상 구간은 지운다
        Db::exec('UPDATE hsb_quizzes SET youtube_id = NULL, start_sec = NULL, end_sec = NULL, cues = NULL WHERE book_id = ?', [$id]);
        apply_videos($id, $videos);
    });
    return ['id' => $id, 'pages' => count($pages), 'quizzes' => count($quizzes), 'regions' => count($regions), 'videos' => count($videos)];
}

