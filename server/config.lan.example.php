<?php
// 사내 랜 공유(lan-run.bat)용 설정 — setup.bat 이 config.lan.php 로 복사하고 비밀값을 랜덤으로 채운다.
// 주소는 'auto' : 접속한 주소(http://<이 PC 랜 IP>:8080)로 서명 URL·리다이렉트를 만든다.
return [
    'db_dsn' => 'sqlite:' . __DIR__ . '/var/lan.sqlite',
    'jwt_secret' => '__RANDOM__',
    'asset_secret' => '__RANDOM__',
    'admin_token' => '__RANDOM__',
    'public_api_url' => 'auto',
    'web_url' => 'auto',
    'app_scheme' => 'haeseolbook',
    'storage_dir' => __DIR__ . '/storage',
    // 사내 검수 모드: 이메일만 입력해 입장(각자 필기·채점 따로 저장). 인터넷에 열지 말 것
    'allow_dev_login' => true,
    'google' => null,
    'kakao' => null,
];
