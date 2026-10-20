//! 해설북 데스크톱 셸.
//! - 창은 출판사 사이트의 PWA(https://.../exam/ebook/)를 그대로 띄운다 (tauri.conf.json)
//! - contentProtected: Windows SetWindowDisplayAffinity / macOS sharingType 으로 화면 캡처 차단 (Linux 미지원)
//! - haeseolbook://auth/callback?code=… 딥링크를 받으면 웹의 /auth/callback 으로 넘겨 로그인을 마친다

use tauri::{Manager, Url};
use tauri_plugin_deep_link::DeepLinkExt;

/// 웹 앱 주소 (끝에 / 포함). 창 URL 과 같아야 한다
const WEB_URL: &str = "https://axexam.mycafe24.com/exam/ebook/";

fn handle_deep_link(app: &tauri::AppHandle, url: &Url) {
    if url.scheme() != "haeseolbook" || url.host_str() != Some("auth") || url.path() != "/callback" {
        return;
    }
    let Some(code) = url.query_pairs().find(|(k, _)| k == "code").map(|(_, v)| v.into_owned()) else { return };
    // 코드는 base64url 문자만 허용 (URL 조작 방지)
    if code.is_empty() || !code.chars().all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_') {
        return;
    }
    if let Some(win) = app.get_webview_window("main") {
        if let Ok(target) = Url::parse(&format!("{WEB_URL}auth/callback?code={code}")) {
            let _ = win.navigate(target);
        }
        let _ = win.unminimize();
        let _ = win.set_focus();
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        // 두 번째 실행(Windows/Linux 에서 딥링크로 열릴 때)은 기존 창으로 넘긴다
        .plugin(tauri_plugin_single_instance::init(|app, argv, _cwd| {
            for arg in argv.iter().skip(1) {
                if let Ok(url) = Url::parse(arg) {
                    handle_deep_link(app, &url);
                }
            }
            if let Some(win) = app.get_webview_window("main") {
                let _ = win.set_focus();
            }
        }))
        .plugin(tauri_plugin_deep_link::init())
        .plugin(tauri_plugin_opener::init())
        .setup(|app| {
            #[cfg(any(windows, target_os = "linux"))]
            {
                // 설치 없이 실행한 개발 빌드에서도 스킴 등록
                let _ = app.deep_link().register_all();
            }
            let handle = app.handle().clone();
            app.deep_link().on_open_url(move |event| {
                for url in event.urls() {
                    handle_deep_link(&handle, &url);
                }
            });
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("해설북 실행 실패");
}
