<?php
// config.php 로 복사해 값을 채운다. config.php 는 저장소에 올리지 않는다.
return [
    // MySQL 운영: 'mysql:host=localhost;dbname=haeseolbook;charset=utf8mb4'
    // 로컬 테스트: 'sqlite:' . __DIR__ . '/var/dev.sqlite'
    'db_dsn'  => 'mysql:host=localhost;dbname=haeseolbook;charset=utf8mb4',
    'db_user' => 'haeseolbook',
    'db_pass' => '',

    // 32바이트 이상 랜덤 문자열 (php -r "echo bin2hex(random_bytes(32));")
    'jwt_secret'   => '',
    'asset_secret' => '',
    // 관리자 화면(/api/admin)에서 IP 허브 패키지를 올릴 때 쓰는 토큰 (32자 이상, 비우면 관리자 기능 꺼짐)
    'admin_token'  => '',

    // 이 API 의 공개 주소 (서명 URL·OAuth 콜백에 사용). 예: https://axexam.mycafe24.com/exam/ebook/api
    'public_api_url' => 'https://example.com/exam/ebook/api',
    // 웹(PWA) 주소(경로 포함). 로그인 완료 후 <web_url>/auth/callback 으로 돌려보낸다. CORS 출처도 여기서 계산
    // 예: https://axexam.mycafe24.com/exam/ebook
    'web_url' => 'https://example.com/exam/ebook',
    // 앱 래퍼(Tauri/Capacitor) 딥링크 스킴
    'app_scheme' => 'haeseolbook',

    // 페이지 이미지 보관 위치 (웹 루트 밖)
    'storage_dir' => __DIR__ . '/storage',

    // 출판사 사이트(그누보드) 회원 로그인 연동: 그누보드 루트의 common.php 절대경로
    // 예: Cafe24 '/home/hosting_users/<아이디>/www/common.php'. 비우면 비활성
    'g5_common' => '',
    'g5_login_url' => '/bbs/login.php',

    // 개발·검수용 이메일 로그인. 운영에서는 false
    'allow_dev_login' => false,

    // 비워두면 해당 로그인 버튼이 숨겨진다
    'google' => ['client_id' => '', 'client_secret' => ''],
    'kakao'  => ['client_id' => '', 'client_secret' => ''],
];
