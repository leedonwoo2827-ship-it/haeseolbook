"""화이트보드형 강의 렌더 — 기존 강의(같은 원고·같은 목소리·같은 시간축)를 손글씨 화이트보드로 다시 굽는다.

    .venv\\Scripts\\python _new\\whiteboard\\wb_render.py --job adsp-26 --only L01
        [--sections s1-01] [--preview 40] [--stills] [--burn] [--workers 4] [--foley-lu 18]

    결과: jobs/<J>/out_wb/<L>/<L>.mp4 (+ .srt · .chapters.json 은 기존 out/<L>/ 에서 복사 — 시간축이 같다)
          parts/<sid>.mp4 · scenes/<sid>.json · stills/*.png

흐름: scene.py(언제 쓰나) → page/(어디에 쓰나·그리기, 헤드리스 Chromium) → 프레임 JPEG → ffmpeg
      → foley.py(마커 소리) + 기존 섹션 mp4 의 음성 → 섹션 mp4 → 강 하나로 잇고 −16 LUFS.
★ TTS 를 다시 돌리지 않는다: 음성은 기존 parts/<sid>.mp4 의 오디오를 그대로 쓴다(F2 · 1.05 표준 유지).
★ 펜·손·커서는 그리지 않는다. 엔진은 lemo-opuscar(MIT) whiteboard 의 wb.js — page/engine/VENDORED.md.
"""
from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(ROOT), str(HERE)]

from longform.s4_stitch import _loudnorm  # noqa: E402
from longform.util import ffprobe_duration, need, read_json  # noqa: E402

import foley  # noqa: E402
from scene import build_section  # noqa: E402

PAGE = HERE / "page"
HOST = "http://wb.local/"
CHUNK_SEC = 60.0


def say(msg: str) -> None:
    print(time.strftime("[%H:%M:%S] ") + msg, flush=True)


# ───────────── 페이지(헤드리스 Chromium) — 포트 없이 route 로 파일을 내준다
def open_page(pw, scene_path: Path, fps: int, burn: bool):
    browser = pw.chromium.launch(args=["--force-color-profile=srgb", "--disable-lcd-text"])
    page = browser.new_page(viewport={"width": 1920, "height": 1080}, device_scale_factor=1)
    errs: List[str] = []
    page.on("pageerror", lambda e: errs.append(str(e)))

    def handle(route):
        rel = route.request.url[len(HOST):].split("?", 1)[0]
        f = scene_path if rel == "scene.json" else (PAGE / rel)
        if not f.is_file():
            return route.fulfill(status=404, body="not found")
        ct = {".js": "text/javascript", ".mjs": "text/javascript", ".json": "application/json",
              ".ttf": "font/ttf", ".html": "text/html"}.get(f.suffix, mimetypes.guess_type(f.name)[0] or "application/octet-stream")
        route.fulfill(status=200, body=f.read_bytes(), headers={"Content-Type": ct, "Access-Control-Allow-Origin": "*"})

    page.route(HOST + "**", handle)
    page.goto(f"{HOST}index.html?scene=scene.json&fps={fps}&burn={1 if burn else 0}")
    try:
        page.wait_for_function("window.READY === true || window.__ERR", timeout=180_000)
    except Exception:
        raise RuntimeError(f"페이지 준비 실패: {scene_path.name} {errs[:3]}")
    if errs:
        raise RuntimeError(f"페이지 오류: {scene_path.name} {errs[:3]}")
    return browser, page


JS_FRAME = """([t, q]) => { const s = window.sig(t);
  if (s !== null && s === window._ps) return null;
  window._ps = s; window.render(t); return window.CV.toDataURL('image/jpeg', q); }"""


def render_chunk(scene_path: str, f0: int, f1: int, fps: int, burn: bool, out: str, crf: int) -> Tuple[str, int, int]:
    """프레임 [f0, f1) → out(mp4, 영상만). 반환 (out, 프레임 수, 새로 그린 프레임 수)."""
    from playwright.sync_api import sync_playwright
    ff = need("ffmpeg")
    enc = subprocess.Popen([ff, "-y", "-hide_banner", "-loglevel", "error", "-f", "image2pipe", "-framerate", str(fps),
                            "-c:v", "mjpeg", "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", str(crf),
                            "-pix_fmt", "yuv420p", "-r", str(fps), "-movflags", "+faststart", out],
                           stdin=subprocess.PIPE)
    drawn = 0
    with sync_playwright() as pw:
        browser, page = open_page(pw, Path(scene_path), fps, burn)
        prev = b""
        for f in range(f0, f1):
            r = page.evaluate(JS_FRAME, [f / fps, .9])
            if r is not None:
                prev = base64.b64decode(r.split(",", 1)[1])
                drawn += 1
            enc.stdin.write(prev)
        browser.close()
    enc.stdin.close()
    if enc.wait() != 0:
        raise RuntimeError(f"ffmpeg 인코딩 실패: {out}")
    return out, f1 - f0, drawn


def probe_scene(scene_path: Path, fps: int, burn: bool, stills_dir: Optional[Path], prefix: str) -> Dict[str, Any]:
    """소리 이벤트·스틸 시각·배치 정보를 받고, 원하면 스틸 PNG 를 뽑는다."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser, page = open_page(pw, scene_path, fps, burn)
        info = page.evaluate("() => ({dur: window.DUR, ev: window.EV, stills: window.STILLS, info: window.INFO})")
        if stills_dir:
            stills_dir.mkdir(parents=True, exist_ok=True)
            for s in info["stills"]:
                b = page.evaluate("t => { window._ps = null; window.render(t); return window.CV.toDataURL('image/png'); }", s["t"])
                (stills_dir / f"{prefix}_{s['name']}.png").write_bytes(base64.b64decode(b.split(",", 1)[1]))
        browser.close()
    return info


def _lufs(src: Path, stream: str = "a:0") -> Optional[float]:
    p = subprocess.run([need("ffmpeg"), "-hide_banner", "-nostats", "-i", str(src), "-map", f"0:{stream}",
                        "-af", "loudnorm=print_format=json", "-f", "null", "-"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    m = re.search(r'"input_i"\s*:\s*"(-?[\d.]+|-inf)"', p.stderr)
    return float(m.group(1)) if m and m.group(1) != "-inf" else None


def mix_section(video: Path, src_part: Path, foley_wav: Path, dur: float, out: Path, foley_lu: float) -> None:
    v_i, f_i = _lufs(src_part), _lufs(foley_wav)
    gain = (v_i - foley_lu - f_i) if (v_i is not None and f_i is not None) else -20.0
    fc = (f"[1:a]atrim=0:{dur:.3f},asetpts=PTS-STARTPTS[v];[2:a]volume={gain:.2f}dB,atrim=0:{dur:.3f}[f];"
          f"[v][f]amix=inputs=2:duration=first:normalize=0[a]")
    subprocess.run([need("ffmpeg"), "-y", "-hide_banner", "-loglevel", "error", "-i", str(video), "-i", str(src_part),
                    "-i", str(foley_wav), "-filter_complex", fc, "-map", "0:v", "-map", "[a]", "-c:v", "copy",
                    "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", "-t", f"{dur:.3f}",
                    "-movflags", "+faststart", str(out)], check=True)


def concat(files: List[Path], out: Path) -> None:
    lst = out.with_suffix(".concat.txt")
    lst.write_text("".join(f"file '{p.as_posix()}'\n" for p in files), encoding="utf-8")
    subprocess.run([need("ffmpeg"), "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0",
                    "-i", str(lst), "-c", "copy", str(out)], check=True)
    lst.unlink(missing_ok=True)


def main() -> None:
    ap = argparse.ArgumentParser(description="화이트보드형 강의 렌더(기존 원고·음성 재사용)")
    ap.add_argument("--job", required=True)
    ap.add_argument("--only", default="", help="강 id, 쉼표로 여럿 (예: L01,L02). 비우면 전부")
    ap.add_argument("--sections", default="", help="섹션 id 만 (예: s1-01)")
    ap.add_argument("--preview", type=float, default=0, help="강 앞쪽 N초만(확인용)")
    ap.add_argument("--stills", action="store_true", help="장마다 스틸 PNG")
    ap.add_argument("--burn", action="store_true", help="자막을 화면에 굽는다(손글씨 라벨)")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--crf", type=int, default=20)
    ap.add_argument("--workers", type=int, default=max(1, min(6, (os.cpu_count() or 4) // 2)))
    ap.add_argument("--foley-lu", type=float, default=18.0, help="마커 소리를 목소리보다 몇 LU 낮게(기본 18)")
    a = ap.parse_args()

    jd = ROOT / "jobs" / a.job
    cur = read_json(jd / "curriculum.json")
    only = [x.strip() for x in a.only.split(",") if x.strip()]
    secs_only = [x.strip() for x in a.sections.split(",") if x.strip()]
    lectures = [L for L in cur["lectures"] if not only or L["id"] in only]
    if not lectures:
        sys.exit(f"강이 없습니다: {a.only}")

    for L in lectures:
        lid = L["id"]
        od = jd / "out_wb" / lid
        (od / "scenes").mkdir(parents=True, exist_ok=True)
        (od / "parts").mkdir(parents=True, exist_ok=True)
        (od / "_work").mkdir(parents=True, exist_ok=True)
        all_secs = [s["id"] for s in L["sections"]]
        say(f"{lid} {L.get('title', '')} — 섹션 {len(all_secs)}개")

        plan: List[Dict[str, Any]] = []
        off = 0.0
        for k, sid in enumerate(all_secs):
            sc = build_section(jd, lid, sid, first=k == 0, last=k == len(all_secs) - 1)
            sp = od / "scenes" / f"{sid}.json"
            sp.write_text(json.dumps(sc, ensure_ascii=False), encoding="utf-8")
            d = sc["dur"]
            take = d if not a.preview else max(0.0, min(d, a.preview - off))
            off += d
            if secs_only and sid not in secs_only:
                continue
            if take <= 0:
                continue
            plan.append({"sid": sid, "scene": sp, "dur": take, "full": d, "src": Path(sc["src_part"])})
        if not plan:
            say("렌더할 섹션이 없습니다")
            continue

        # 1) 소리 이벤트·스틸
        for p in plan:
            info = probe_scene(p["scene"], a.fps, a.burn, od / "stills" if a.stills else None, p["sid"])
            p["ev"] = info["ev"]
            say(f"  {p['sid']}: {len(p['ev'])}획 · 보드 {info['info']['cols']}×{info['info']['rows']} · "
                f"{p['dur']:.1f}초" + (f" · 스틸 {len(info['stills'])}장" if a.stills else ""))

        # 2) 프레임 → 영상(섹션을 60초 조각으로 나눠 병렬)
        tasks = []
        reused = 0
        for p in plan:
            nf = int(round(p["dur"] * a.fps))
            step = int(CHUNK_SEC * a.fps)
            p["chunks"] = []
            for i, f0 in enumerate(range(0, nf, step)):
                out = od / "_work" / f"{p['sid']}_{i:03d}.mp4"
                p["chunks"].append(out)
                f1 = min(nf, f0 + step)
                # ★ 이어서 하기: 앞서 끝까지 구운 조각(길이가 맞는 것)은 다시 굽지 않는다(창이 닫혀 멈춘 뒤 다시 눌렀을 때)
                if out.exists() and abs((ffprobe_duration(out) or 0) - (f1 - f0) / a.fps) < 0.2:
                    reused += 1
                    continue
                tasks.append((str(p["scene"]), f0, f1, a.fps, a.burn, str(out), a.crf))
        if reused:
            say(f"  앞서 구운 조각 {reused}개는 그대로 씁니다")
        say(f"  프레임 렌더: 조각 {len(tasks)}개 · 워커 {a.workers}")
        t_start, done, frames, drawn = time.time(), 0, 0, 0
        with ProcessPoolExecutor(max_workers=a.workers) as ex:
            futs = [ex.submit(render_chunk, *t) for t in tasks]
            for fu in as_completed(futs):
                _, nfr, ndr = fu.result()
                done += 1
                frames += nfr
                drawn += ndr
                el = time.time() - t_start
                say(f"    {done}/{len(tasks)} 조각 · 새로 그린 프레임 {drawn}/{frames} · {el / 60:.1f}분 경과"
                    f" · 남은 시간 약 {el / done * (len(tasks) - done) / 60:.1f}분")

        # 3) 섹션: 영상 잇기 + 마커 소리 + 기존 음성
        parts = []
        for p in plan:
            vid = od / "_work" / f"{p['sid']}.video.mp4"
            concat(p["chunks"], vid)
            fw = od / "_work" / f"{p['sid']}.foley.wav"
            n = foley.render(p["ev"], p["dur"], fw)
            part = od / "parts" / f"{p['sid']}.mp4"
            mix_section(vid, p["src"], fw, p["dur"], part, a.foley_lu)
            parts.append(part)
            say(f"  {p['sid']} 섹션 완성 · 마커 소리 {n}개 → {part.relative_to(ROOT)}")

        # 4) 강 하나로 잇고 음량 맞추기
        raw = od / f"{lid}.raw.mp4"
        concat(parts, raw)
        tag = "" if not (a.preview or secs_only) else ".preview"
        out = od / f"{lid}{tag}.mp4"
        _loudnorm(raw, out)
        raw.unlink(missing_ok=True)
        if not tag:
            for ext in (".srt", ".chapters.json"):
                src = jd / "out" / lid / f"{lid}{ext}"
                if src.exists():
                    shutil.copy2(src, od / src.name)
            old = jd / "out" / lid / f"{lid}.mp4"
            if old.exists():
                d_old, d_new = ffprobe_duration(old), ffprobe_duration(out)
                say(f"  길이: 기존 {d_old:.2f}초 · 화이트보드 {d_new:.2f}초 (차이 {d_new - d_old:+.2f}초)")
        shutil.rmtree(od / "_work", ignore_errors=True)
        say(f"{lid} 완료 → {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
