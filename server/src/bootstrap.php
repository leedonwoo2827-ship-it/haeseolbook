<?php
declare(strict_types=1);

if (PHP_VERSION_ID < 80100) {
    http_response_code(500);
    exit('PHP 8.1 이상이 필요합니다');
}

require __DIR__ . '/core.php';
require __DIR__ . '/Jwt.php';
require __DIR__ . '/services.php';
require __DIR__ . '/seed.php';
require __DIR__ . '/import.php';
require __DIR__ . '/admin.php';
require __DIR__ . '/routes.php';
