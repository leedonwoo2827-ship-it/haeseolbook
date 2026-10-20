<?php
declare(strict_types=1);

// 해설북 API 진입점. 이 폴더(public)만 웹에 노출하고 src/, storage/, config.php 는 웹 루트 밖에 둔다.
require dirname(__DIR__) . '/src/bootstrap.php';

Hsb\handle(Hsb\Request::fromGlobals())->send();
