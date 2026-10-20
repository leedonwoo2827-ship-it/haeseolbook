<?php
declare(strict_types=1);

/**
 * 관리 CLI
 *   php bin/hsb.php migrate                 schema.mysql.sql 적용 (SQLite 면 자동 변환)
 *   php bin/hsb.php seed <buildDir>...      파이프라인 산출물(content/build/<bookId>/)을 DB·스토리지에 적재
 *   php bin/hsb.php video <buildDir> <video_map.json>   AI 해설영상 매핑만 갱신
 *
 * buildDir 구성 (tools/pipeline 이 생성)
 *   book.json, pages.json, pages/{xs,sm,hi}/<n>.webp, regions.json, quizzes.json,
 *   solutions.json(선택), video_map.json(선택)
 *
 * video_map.json (AI 가 해설영상을 만들며 역으로 넘겨주는 좌표)
 *   [{ "no": 1, "youtubeId": "xxxxxxxxxxx", "startSec": 12.0, "endSec": 95.5,
 *      "pageNo": 1, "bbox": {"x":..,"y":..,"w":..,"h":..},          // 선택: 문항 영역(없으면 regions.json 사용)
 *      "cues": [{"t": 15.2, "pageNo": 1, "x": 0.31, "y": 0.42}, ...] // 선택: 포인터 트랙 }]
 */

require dirname(__DIR__) . '/src/bootstrap.php';



use Hsb\Db;
use function Hsb\Seed\{apply_videos, read_json, seed, validate_video_map};

$cmd = $argv[1] ?? '';
try {
switch ($cmd) {
    case 'migrate':
        Db::migrate(dirname(__DIR__) . '/schema.mysql.sql');
        echo "migrated\n";
        break;
    case 'seed':
        $dirs = array_slice($argv, 2) ?: throw new Hsb\Seed\SeedError('buildDir 를 지정하세요');
        foreach ($dirs as $d) echo 'seeded ' . json_encode(seed($d), JSON_UNESCAPED_UNICODE) . "\n";
        break;
    case 'video':
        [$dir, $file] = [$argv[2] ?? throw new Hsb\Seed\SeedError('buildDir 를 지정하세요'), $argv[3] ?? throw new Hsb\Seed\SeedError('video_map.json 을 지정하세요')];
        $book = read_json($dir, 'book.json');
        $vm = json_decode((string) file_get_contents($file), true) ?? throw new Hsb\Seed\SeedError('video_map JSON 오류');
        Db::tx(fn () => apply_videos($book['id'], validate_video_map($vm)));
        echo "video map applied\n";
        break;
    default:
        echo "사용법: php bin/hsb.php migrate | seed <buildDir>... | video <buildDir> <video_map.json>\n";
        exit($cmd === '' ? 0 : 1);
}
} catch (Hsb\Seed\SeedError $e) {
    fwrite(STDERR, '오류: ' . $e->getMessage() . "\n");
    exit(1);
}
