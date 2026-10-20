<?php
declare(strict_types=1);

// Cafe24 배포용 API 진입점 → www/exam/ebook/api/index.php 에 올린다.
// 코드·설정·이미지(hsb/)는 웹 루트(www) 밖에 두고 여기서만 불러온다.
// HSB_ROOT 는 build.sh 가 실제 경로로 바꿔 넣는다 (예: /home/hosting_users/axexam/hsb).
const HSB_ROOT = '__HSB_ROOT__';

require HSB_ROOT . '/src/bootstrap.php';

Hsb\handle(Hsb\Request::fromGlobals())->send();
