"""s6 유튜브 업로드 — 로그인된 시스템 Chrome(이 저장소의 profiles/<계정>)을 CDP 로 움직인다(Data API·OAuth 불필요).

처음 한 번: youtube-login.bat → 열린 Chrome 에서 Google 로그인 + 올릴 채널 선택.
업로드 순서: 파일 첨부(CDP DOM.setFileInputFiles — 50MB 넘는 영상도) → 제목·설명(챕터) → 썸네일 → 태그 → 재생목록
            → 아동용 아님 → 다음×3 → 공개 범위(기본 일부공개) → 업로드 완료 대기 → 저장 → watch URL
★ 파일을 넣은 뒤에는 다시 시도하지 않는다(초안이 중복으로 생김). 멈추면 열린 Studio 창에서 사람이 마무리.
화면 셀렉터는 SEL·TEXT 에만 모아 두었다 — Studio 화면이 바뀌면 여기만 고친다.
"""
from __future__ import annotations

import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import ROOT
from .log import log

HOME = "https://studio.youtube.com/"
UPLOAD = "https://www.youtube.com/upload"
PROFILES = ROOT / "profiles"
LOGS = ROOT / "logs" / "post"
SESSION_COOKIES = ("SAPISID", "__Secure-3PAPISID", "LOGIN_INFO")

SEL: Dict[str, Any] = {
    "picker": "ytcp-uploads-file-picker",
    "file": 'ytcp-uploads-file-picker input[type="file"]',
    "select_btn": "#select-files-button",
    "title": "#title-textarea #textbox",
    "desc": "#description-textarea #textbox",
    "not_kids": 'tp-yt-paper-radiobutton[name="VIDEO_MADE_FOR_KIDS_NOT_MFK"]',
    "next": "#next-button",
    "done": "#done-button",
    "vis": {"public": 'tp-yt-paper-radiobutton[name="PUBLIC"]',
            "unlisted": 'tp-yt-paper-radiobutton[name="UNLISTED"]',
            "private": 'tp-yt-paper-radiobutton[name="PRIVATE"]'},
    "video_url": "ytcp-video-info a.ytcp-video-info, .video-url-fadeable a",
    "progress": "ytcp-video-upload-progress .progress-label, ytcp-video-upload-progress",
    "close": "#close-button, ytcp-button#close-button",
    "schedule_open": "#second-container-expand-button",
    "date_trigger": "#datepicker-trigger",
    "date_input": "ytcp-date-picker tp-yt-paper-input input, ytcp-date-picker input",
    "time_input": "#time-of-day-container input, ytcp-datetime-picker #time-of-day-container tp-yt-paper-input input",
    "more": "#toggle-button",
    "tags": "#tags-container input#text-input, input[aria-label*='Tags'], input[aria-label*='태그']",
    "thumb": "#file-loader, ytcp-thumbnails-compact-editor-uploader input[type='file'], "
             "ytcp-video-custom-still-editor input[type='file']",
    "altered_yes": "tp-yt-paper-radiobutton[name='VIDEO_HAS_ALTERED_CONTENT_YES']",
    "uploaded": re.compile(r"(업로드 완료|Upload complete|확인 완료|검사가 완료|검사 완료|문제가 없습니다|Checks complete|"
                           r"No issues|처리|Processing|SD|HD|저작권|Copyright)", re.I),
}
TEXT: Dict[str, Any] = {
    "not_kids": re.compile(r"(아니요, 아동용이 아닙니다|No, it.s not made for kids)"),
    "public": re.compile(r"^(공개|Public)$"),
    "unlisted": re.compile(r"^(일부 공개|Unlisted)$"),
    "private": re.compile(r"^(비공개|Private)$"),
    "next": re.compile(r"^(다음|Next)$"),
    "done": re.compile(r"^(저장|게시|예약|Save|Publish|Schedule)$"),
    "more": re.compile(r"^(자세히 보기|Show more|더보기)$"),
    "altered": re.compile(r"(변경되거나 합성된 콘텐츠|Altered content)"),
}


TEXT_PL_OPEN = re.compile(r"^(선택|Select)$")
TEXT_PL_DONE = re.compile(r"^(완료|Done)$")
TEXT_PL_NEW = re.compile(r"^(새 재생목록|New playlist)$")
TEXT_PL_CREATE = re.compile(r"^(만들기|Create)$")


class PostError(RuntimeError):
    pass


# ── Chrome ────────────────────────────────────────────────────────────────
def chrome_path() -> str:
    cands = []
    if sys.platform.startswith("win"):
        cands += [r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                  r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                  str(Path.home() / r"AppData\Local\Google\Chrome\Application\chrome.exe")]
    elif sys.platform == "darwin":
        cands += ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"]
    else:
        cands += [shutil.which(n) or "" for n in ("google-chrome", "google-chrome-stable", "chromium")]
    for c in cands:
        if c and Path(c).exists():
            return c
    raise PostError("Google Chrome 을 찾지 못했습니다 — 설치 후 다시 실행하세요")


def _port_open(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


def _wait_port(port: int, tries: int = 60) -> bool:
    for _ in range(tries):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1)
            return True
        except Exception:
            time.sleep(0.5)
    return False


def _account(account: Optional[str]) -> Dict[str, Any]:
    from . import accounts
    return accounts.get(account)


def ensure_chrome(account: Optional[str] = None, port: Optional[int] = None, url: str = HOME) -> bool:
    """그 계정 프로필 Chrome 을 디버그 포트로 화면 왼쪽에 띄운다(오른쪽은 올리기 패널). 이미 떠 있으면 그대로. 새로 띄웠으면 True."""
    acc = _account(account)
    port = port or int(acc["port"])
    if _port_open(port):
        return False
    profile = PROFILES / acc["name"]
    profile.mkdir(parents=True, exist_ok=True)
    subprocess.Popen([chrome_path(), f"--user-data-dir={profile}", f"--remote-debugging-port={port}",
                      "--no-first-run", "--no-default-browser-check", "--window-size=1400,950", url])
    if not _wait_port(port):
        raise PostError("Chrome 디버그 포트가 열리지 않습니다 — 같은 프로필 Chrome 이 떠 있으면 닫고 다시 하세요")
    try:
        place(port, "left")
    except Exception:       # 배치는 보기 좋으라고 하는 일
        pass
    return True


# ── 올리기 패널: 왼쪽 YouTube Studio Chrome + 오른쪽 좁은 패널(Chrome 앱 창) ─────────
PANEL_WIDTH = 460
PANEL_PORT = 9380


def place(port: int, side: str) -> None:
    """창을 화면 왼쪽(YouTube) 또는 오른쪽(패널)에 붙인다.
    실행 인자 좌표는 Windows 배율에 따라 어긋나므로, 창이 뜬 뒤 Chrome 이 아는 화면 영역(screen.avail*)으로
    CDP Browser.setWindowBounds 를 건다."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        br = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
        ctx = br.contexts[0]
        page = next((p for p in ctx.pages if not p.url.startswith("devtools")), None) or ctx.new_page()
        ax, ay, aw, ah = page.evaluate("[screen.availLeft || 0, screen.availTop || 0, screen.availWidth, screen.availHeight]")
        cdp = ctx.new_cdp_session(page)
        wid = cdp.send("Browser.getWindowForTarget")["windowId"]
        cdp.send("Browser.setWindowBounds", {"windowId": wid, "bounds": {"windowState": "normal"}})
        b = ({"left": ax + aw - PANEL_WIDTH, "top": ay, "width": PANEL_WIDTH, "height": ah} if side == "right"
             else {"left": ax, "top": ay, "width": max(700, aw - PANEL_WIDTH), "height": ah})
        cdp.send("Browser.setWindowBounds", {"windowId": wid, "bounds": b})
        cdp.detach()


def _is_panel(port: int, ui_port: int) -> bool:
    import json
    try:
        tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=1))
        return any(str(t.get("url", "")).startswith(f"http://127.0.0.1:{ui_port}/") for t in tabs)
    except Exception:
        return False


def open_panel(ui_port: int) -> bool:
    """오른쪽 끝에 올리기 패널을 붙인다. 이미 떠 있으면 자리만 맞춘다."""
    port = PANEL_PORT
    if not (_port_open(port) and _is_panel(port, ui_port)):
        if _port_open(port):            # 다른 도구가 쓰는 포트면 위로 비어 있는 포트
            port = next(p for p in range(PANEL_PORT - 40, PANEL_PORT) if not _port_open(p))
        subprocess.Popen([chrome_path(), f"--app=http://127.0.0.1:{ui_port}/panel",
                          f"--user-data-dir={PROFILES / '_panel'}", f"--remote-debugging-port={port}",
                          "--no-first-run", "--no-default-browser-check", f"--window-size={PANEL_WIDTH},900"],
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if not _wait_port(port):
            return False
        time.sleep(1.0)
    place(port, "right")
    return True


def channel_of(vid: str) -> Optional[str]:
    """올라간 영상의 채널 이름(oEmbed — 일부공개도 됨). 잘못된 채널로 올렸는지 바로 알아보려고."""
    import json
    try:
        r = urllib.request.urlopen(f"https://www.youtube.com/oembed?url=https://youtu.be/{vid}&format=json", timeout=10)
        return json.load(r).get("author_name")
    except Exception:
        return None


class Session:
    def __init__(self, account: Optional[str] = None, port: Optional[int] = None):
        acc = _account(account)
        self.account, self.port = acc["name"], port or int(acc["port"])

    def __enter__(self) -> "Session":
        from playwright.sync_api import sync_playwright
        ensure_chrome(self.account, self.port)
        self._pw = sync_playwright().start()
        self.browser = self._pw.chromium.connect_over_cdp(f"http://127.0.0.1:{self.port}")
        self.ctx = self.browser.contexts[0] if self.browser.contexts else self.browser.new_context()
        pages = [p for p in self.ctx.pages if "youtube." in p.url]
        self.page = pages[0] if pages else (self.ctx.pages[0] if self.ctx.pages else self.ctx.new_page())
        self.page.bring_to_front()
        return self

    def __exit__(self, *exc) -> None:
        try:
            self._pw.stop()        # 연결만 끊는다 — Chrome 창은 남는다
        except Exception:
            pass

    def logged_in(self) -> bool:
        names = {c["name"] for c in self.ctx.cookies(["https://www.youtube.com", "https://studio.youtube.com"])}
        return any(n in names for n in SESSION_COOKIES)

    def shot(self, name: str) -> None:
        LOGS.mkdir(parents=True, exist_ok=True)
        try:
            self.page.screenshot(path=str(LOGS / f"{time.strftime('%m%d-%H%M%S')}-{name}.png"))
        except Exception:
            pass


def open_login(account: Optional[str] = None) -> None:
    if not ensure_chrome(account, url=HOME):
        with Session(account) as s:
            s.page.goto(HOME)
    log(f"[{_account(account)['label']}] 열린 Chrome 창에서 Google 로그인 후, 올릴 채널이 선택돼 있는지 확인하세요. 창은 닫지 않아도 됩니다.")


def is_logged_in(account: Optional[str] = None) -> bool:
    with Session(account) as s:
        return s.logged_in()


# ── 화면 조작 도우미 ───────────────────────────────────────────────────────
def _click(page, css: str, text=None, *, role: str = "radio", timeout: int = 20_000) -> None:
    cands = [page.locator(css).first]
    if text is not None:
        cands += [page.get_by_role(role, name=text).first, page.get_by_text(text).first]
    deadline, last = time.time() + timeout / 1000, None
    while time.time() < deadline:
        for c in cands:
            try:
                if c.count() and c.is_visible():
                    c.scroll_into_view_if_needed(timeout=3_000)
                    c.click(timeout=5_000)
                    return
            except Exception as e:  # noqa: BLE001
                last = e
        time.sleep(0.5)
    raise PostError(f"화면에서 찾지 못했습니다 ({text.pattern if text is not None else css}): {str(last)[:120]}")


def _fill(page, css: str, value: str) -> None:
    box = page.locator(css).first
    box.wait_for(state="visible", timeout=30_000)
    box.click()
    page.keyboard.press("Control+A")
    page.keyboard.press("Delete")
    page.keyboard.insert_text(value)
    time.sleep(0.4)


_FIND_TAGGED = """(function f(root){
  const el = root.querySelector('[data-hsb-file]'); if (el) return el;
  for (const n of root.querySelectorAll('*')) if (n.shadowRoot) { const r = f(n.shadowRoot); if (r) return r; }
  return null; })(document)"""


def _set_files_cdp(s: Session, target, path: Path) -> None:
    """파일 칸에 경로만 알려 Chrome 이 디스크에서 직접 읽게 한다(Playwright 전송은 50MB 제한)."""
    target.evaluate("el => { document.querySelectorAll('[data-hsb-file]').forEach(x => x.removeAttribute('data-hsb-file'));"
                    " el.setAttribute('data-hsb-file', '1') }")
    cdp = s.ctx.new_cdp_session(s.page)
    try:
        oid = cdp.send("Runtime.evaluate", {"expression": _FIND_TAGGED})["result"].get("objectId")
        if not oid:
            raise PostError("파일 칸을 찾지 못했습니다")
        cdp.send("DOM.setFileInputFiles", {"files": [str(Path(path).resolve())], "objectId": oid})
    finally:
        try:
            cdp.detach()
        except Exception:
            pass


def _attach_video(s: Session, video: Path) -> bool:
    page = s.page
    try:
        page.locator(SEL["picker"]).first.wait_for(state="visible", timeout=60_000)
    except Exception:
        return False
    time.sleep(1.5)
    for attempt in (1, 2):
        try:
            if attempt == 1:
                _set_files_cdp(s, page.locator(SEL["file"]).first, video)
            else:
                with page.expect_file_chooser(timeout=15_000) as fc:
                    page.locator(SEL["select_btn"]).first.click()
                _set_files_cdp(s, fc.value.element, video)
            page.locator(SEL["title"]).first.wait_for(state="visible", timeout=45_000)
            return True
        except Exception:
            s.shot(f"attach{attempt}")
    return False


def _video_url(page, timeout: int) -> Optional[str]:
    try:
        return page.locator(SEL["video_url"]).first.get_attribute("href", timeout=timeout)
    except Exception:
        return None


def _wait_uploaded(s: Session, limit: int = 3600) -> None:
    page, t0, last, since = s.page, time.time(), "", time.time()
    while time.time() - t0 < limit:
        try:
            txt = page.locator(SEL["progress"]).first.inner_text(timeout=3_000).strip()
        except Exception:
            txt = ""
        if txt != last:
            log(f"    진행: {txt[:70]}")
            last, since = txt, time.time()
        uploading = bool(re.search(r"(업로드 중|Uploading|\d+\s*%)", txt))
        if txt and not uploading and SEL["uploaded"].search(txt):
            return
        if txt and not uploading and time.time() - since > 30:
            try:
                btn = page.locator(SEL["done"]).first
                if btn.is_enabled() and btn.get_attribute("aria-disabled") != "true":
                    return
            except Exception:
                pass
        time.sleep(2)
    raise PostError("업로드가 60분 안에 끝나지 않았습니다")


def _set_playlist(s: "Session", name: str) -> bool:
    """세부정보 「재생목록」에서 name 을 체크. 없으면 「새 재생목록」으로 만든다. 못 하면 경고만 — 업로드는 계속."""
    page = s.page
    name = (name or "").strip()
    if not name:
        return False
    try:
        box = page.locator("ytcp-video-metadata-playlists").first
        box.scroll_into_view_if_needed(timeout=8_000)
        trig = box.locator("ytcp-text-dropdown-trigger, ytcp-dropdown-trigger, #basics").first
        (trig if trig.count() else box.get_by_text(TEXT_PL_OPEN).first).click(timeout=8_000)
        dlg = page.locator("ytcp-playlist-dialog, tp-yt-paper-dialog:visible").last
        dlg.wait_for(state="visible", timeout=10_000)
        time.sleep(0.8)
        item = dlg.get_by_text(name, exact=True).first
        if not item.count():
            log(f"  · 재생목록 「{name}」이 없어 새로 만듭니다")
            dlg.get_by_role("button", name=TEXT_PL_NEW).first.click(timeout=8_000)
            time.sleep(0.6)
            menu_new = page.get_by_text(TEXT_PL_NEW)
            if menu_new.count() > 1:
                menu_new.last.click(timeout=5_000)
            time.sleep(0.8)
            form = page.locator("ytcp-playlist-creation-dialog, ytcp-dialog:visible").last
            form.locator("textarea, #textbox, input").first.click(timeout=8_000)
            page.keyboard.insert_text(name)
            form.get_by_role("button", name=TEXT_PL_CREATE).first.click(timeout=8_000)
            time.sleep(2.5)
        else:
            item.click(timeout=8_000)
        time.sleep(0.6)
        dlg.get_by_role("button", name=TEXT_PL_DONE).first.click(timeout=8_000)
        time.sleep(0.8)
        log(f"  · 재생목록 「{name}」에 넣었습니다")
        return True
    except Exception:
        s.shot("playlist-fail")
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
        log(f"  △ 재생목록 「{name}」을 고르지 못했습니다 — Studio 에서 직접 넣어 주세요(업로드는 계속)")
        return False


def watch_url(url: Optional[str]) -> Optional[str]:
    m = re.search(r"(?:shorts/|v=|youtu\.be/)([A-Za-z0-9_-]{6,})", url or "")
    return f"https://www.youtube.com/watch?v={m.group(1)}" if m else url


def video_id(url: Optional[str]) -> Optional[str]:
    m = re.search(r"(?:v=|youtu\.be/|shorts/|/video/)([A-Za-z0-9_-]{11})", url or "")
    return m.group(1) if m else None


def description(script: Dict[str, Any], chapters: List[str]) -> str:
    yt = script.get("youtube") or {}
    parts = ["\n".join(yt.get("hook_lines") or [])]
    if chapters:
        parts.append("\n".join(chapters))
    parts.append("\n".join(yt.get("summary") or []))
    tags = [t for t in (yt.get("tags") or [])][:5]
    parts.append(" ".join("#" + re.sub(r"\s+", "", t) for t in tags))
    return "\n\n".join(p for p in parts if p.strip())[:4900]


_ROWS_JS = """() => [...document.querySelectorAll('ytcp-video-row')].slice(0, 10).map(r => {
  const a = r.querySelector('a[href*="/video/"]'); const t = r.querySelector('#video-title');
  return {t: t ? t.textContent.trim() : '', h: a ? a.getAttribute('href') : ''}; })"""


def _find_url_by_title(s: Session, title: str) -> Optional[str]:
    """Studio 「채널 콘텐츠」 최신 목록에서 같은 제목의 영상 ID 를 찾는다(2026-10-20: 업로드 창에서 링크를 못 읽은 일이 있었다)."""
    page = s.page
    try:
        m = re.search(r"/channel/(UC[\w-]+)", page.url)
        if not m:                                   # studio.youtube.com/ 은 잠시 뒤 /channel/UC… 로 바뀐다
            page.goto(HOME, wait_until="domcontentloaded")
            for _ in range(20):
                m = re.search(r"/channel/(UC[\w-]+)", page.url)
                if m:
                    break
                time.sleep(1)
        if not m:
            raise PostError("채널 주소를 알 수 없어요")
        page.goto(f"https://studio.youtube.com/channel/{m.group(1)}/videos/upload", wait_until="domcontentloaded")
        want = re.sub(r"\s+", " ", title).strip()[:40]
        for _ in range(15):
            time.sleep(2)
            for r in page.evaluate(_ROWS_JS) or []:
                vid = re.search(r"/video/([A-Za-z0-9_-]{11})", r.get("h") or "")
                if vid and re.sub(r"\s+", " ", r.get("t") or "").strip().startswith(want):
                    url = f"https://www.youtube.com/watch?v={vid.group(1)}"
                    log(f"  · 영상 주소를 콘텐츠 목록에서 찾았어요: {url}")
                    return url
    except Exception as e:      # noqa: BLE001
        log(f"  콘텐츠 목록에서 주소 찾기 실패: {e}")
    log("  △ 영상 주소를 못 찾았어요 — Studio 「콘텐츠」에서 확인해 주세요")
    return None


# ── 예약 공개 (Studio 「예약」 칸 — 업로드는 지금, 공개는 그 시각. PC 가 꺼져 있어도 된다) ──────────
def _date_text(sample: str, when: datetime) -> str:
    """칸에 적힌 꼴을 흉내 낸다 — 한국어 「2026. 10. 5.」, 영어 「Oct 5, 2026」"""
    if re.search(r"[A-Za-z]{3}", sample or ""):
        return f"{when:%b} {when.day}, {when.year}"
    return f"{when.year}. {when.month}. {when.day}."


def _time_text(sample: str, when: datetime) -> str:
    h12 = when.hour % 12 or 12
    if "오전" in (sample or "") or "오후" in (sample or ""):
        return f"{'오전' if when.hour < 12 else '오후'} {h12}:{when.minute:02d}"
    if re.search(r"AM|PM", sample or "", re.I):
        return f"{h12}:{when.minute:02d} {'AM' if when.hour < 12 else 'PM'}"
    return when.strftime("%H:%M")


def _set_schedule(s: "Session", when: datetime) -> None:
    page = s.page
    page.locator(SEL["schedule_open"]).first.click(timeout=10_000)
    time.sleep(0.8)
    page.locator(SEL["date_trigger"]).first.click(timeout=10_000)
    di = page.locator(SEL["date_input"]).first
    di.wait_for(state="visible", timeout=10_000)
    txt = _date_text(di.input_value(), when)
    di.fill(txt)
    di.press("Enter")
    time.sleep(0.6)
    ti = page.locator(SEL["time_input"]).first
    ti.wait_for(state="visible", timeout=10_000)
    ttxt = _time_text(ti.input_value(), when)
    ti.click()
    ti.fill(ttxt)
    ti.press("Enter")
    time.sleep(0.6)
    log(f"  예약 입력: {txt} {ttxt}")
    s.shot("schedule-set")


# ── 업로드 ───────────────────────────────────────────────────────────────
def upload(script: Dict[str, Any], video: Path, *, chapters: List[str], thumb: Optional[Path] = None,
           visibility: str = "unlisted", account: Optional[str] = None, dry_run: bool = False,
           playlist: str = "", when: Optional[datetime] = None) -> Dict[str, Any]:
    """when 이 있으면 YouTube 예약 공개(그 시각에 공개), 없으면 visibility 로 바로 게시."""
    yt = script.get("youtube") or {}
    title = (yt.get("title") or script.get("title") or "")[:100]
    desc = description(script, chapters)
    with Session(account) as s:
        page = s.page
        page.on("dialog", lambda d: d.dismiss())
        log("  ① 업로드 창 여는 중")
        page.goto(UPLOAD, wait_until="domcontentloaded")
        if "accounts.google." in page.url or not s.logged_in():
            s.shot("not-logged-in")
            raise PostError("유튜브 로그인이 안 되어 있습니다 — youtube-login.bat 으로 먼저 로그인하세요")
        log("  ② 영상 파일 넣는 중")
        if not _attach_video(s, video):
            raise PostError("영상 파일이 업로드 창에 들어가지 않았습니다(초안 없음) — 다시 실행해도 됩니다")
        early = _video_url(page, 15_000)
        try:
            log("  ③ 제목·설명(챕터)")
            _fill(page, SEL["title"], title)
            _fill(page, SEL["desc"], desc)
            if thumb and thumb.exists():
                try:
                    box = page.locator(SEL["thumb"]).first
                    box.wait_for(state="attached", timeout=15_000)
                    _set_files_cdp(s, box, thumb)
                    time.sleep(3)
                except Exception:
                    log("  △ 썸네일 칸을 못 찾았습니다(채널 전화번호 인증 필요할 수 있음) — Studio 에서 직접 넣으세요")
            try:
                try:
                    _click(page, SEL["more"], TEXT["more"], role="button", timeout=8_000)
                except PostError:
                    pass
                box = page.locator(SEL["tags"]).first
                box.wait_for(state="visible", timeout=10_000)
                box.click()
                page.keyboard.insert_text(", ".join((yt.get("tags") or [])[:15]) + ",")
            except Exception:
                log("  △ 태그 칸을 못 찾아 건너뜀")
            if playlist:
                _set_playlist(s, playlist)
            log("  ④ 아동용 아님")
            _click(page, SEL["not_kids"], TEXT["not_kids"], timeout=30_000)
            for _ in range(3):
                _click(page, SEL["next"], TEXT["next"], role="button", timeout=30_000)
                time.sleep(1.5)
            if when:
                log(f"  ⑤ 예약 공개: {when:%m월 %d일 %H:%M}")
                _set_schedule(s, when)
            else:
                log(f"  ⑤ 공개 범위: {visibility}")
                _click(page, SEL["vis"][visibility], TEXT[visibility])
        except Exception as e:
            s.shot("stopped")
            raise PostError(f"{str(e)[:200]} — 영상은 이미 들어갔습니다. 열린 Studio 창에서 나머지를 직접 마무리하세요"
                            " (다시 실행하면 초안이 하나 더 생깁니다)")
        url = watch_url(early or _video_url(page, 5_000))
        if dry_run:
            s.shot("ready")
            return {"dry_run": True, "url": url}
        log("  ⑥ 업로드 완료 기다리는 중…")
        _wait_uploaded(s)
        _click(page, SEL["done"], TEXT["done"], role="button", timeout=30_000)
        time.sleep(3)
        s.shot("posted")
        try:
            page.locator(SEL["close"]).first.click(timeout=10_000)
        except Exception:
            pass
        if not url:                       # 업로드 창에서 주소를 못 읽었으면 채널 콘텐츠 목록에서 제목으로
            url = _find_url_by_title(s, title)
        log(f"  ⑦ 끝: {url}")
        return {"url": url, "videoId": video_id(url), "title": title, "visibility": "scheduled" if when else visibility,
                "scheduled_for": when.strftime("%Y-%m-%d %H:%M") if when else None, "playlist": playlist,
                "account": s.account, "at": datetime.now().isoformat(timespec="seconds")}
