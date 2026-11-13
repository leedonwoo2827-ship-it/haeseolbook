"""s7 이북 연동: 영상 장(챕터) 시각 → 문항별 해설 구간 video_map.json, 판서 위치 → 포인터 트랙(cues)
→ IP 허브 패키지(.hsbpkg.zip) → 로컬 해설북 서버에 import.

문항 N: startSec = N번 장 시작, endSec = 다음 장 시작. cues = 그 문항 판서들(시각·원문 0–1 좌표) — 이북에서
영상이 재생되면 빨간 점이 강사가 표시하는 자리를 따라간다.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import ROOT
from .job import Job, read_json, write_json
from .log import log


def php_exe() -> Optional[str]:
    local = ROOT / "tools" / "php" / "php.exe"
    return str(local) if local.exists() else shutil.which("php")


def video_map(job: Job, youtube_id: str) -> List[Dict[str, Any]]:
    timing = read_json(job.audio / "timing.json")
    located = read_json(job.boards / "marks.located.json", {}) or {}
    chs = timing["chapters"]
    out = []
    for i, ch in enumerate(chs):
        if not ch.get("quiz"):
            continue
        end = chs[i + 1]["start"] if i + 1 < len(chs) else timing["duration"]
        cues = [{"t": round(m["t"], 2), "pageNo": m["pageNo"], "x": m["norm"][0], "y": m["norm"][1]}
                for m in located.get(str(ch["quiz"]), [])]
        out.append({"no": ch["quiz"], "youtubeId": youtube_id, "startSec": round(ch["start"], 2),
                    "endSec": round(end, 2), "cues": sorted(cues, key=lambda c: c["t"])})
    return out


def attach_figures(job: Job) -> int:
    """모의고사: 원천 문항(<교재>/02/<mNN>-<번호>.md)의 「## 해설」 그림을 이북 해설 끝에 붙인다(2026-11-11 — 해설 칸에 그림이 안 나옴).
    그림은 book/files/<이름>.svg 로 싣고 images.json 에 목록 — 해설 Markdown 의 ![설명](img:이름) 를 이북이 서명 주소로 보여 준다.
    여러 번 돌려도 같은 결과(예전에 붙인 그림 줄은 지우고 다시)."""
    import re
    if job.setting("kind") != "mock":
        return 0
    full = Path(job.meta.get("paperFull") or job.meta["paper"])        # <교재>/07/<mNN>/exam.pdf
    src02, rc = full.parent.parent.parent / "02", job.meta["round"]
    sols = read_json(job.book / "solutions.json", []) or []
    fdir = job.book / "files"
    names: List[str] = []
    for s in sols:
        md = re.sub(r"\n*!\[[^\]]*\]\(img:[^)]+\)\n*", "\n", s.get("markdown", "")).rstrip()
        f = src02 / f"{rc}-{int(s['no']):02d}.md"
        if f.exists():
            parts = re.split(r"^##\s*해설\s*$", f.read_text(encoding="utf-8"), flags=re.M)
            sec = re.split(r"^##\s", parts[1], flags=re.M)[0] if len(parts) > 1 else ""
            for k, (alt, rel) in enumerate(re.findall(r"!\[([^\]]*)\]\(([^)]+)\)", sec), 1):
                pic = (f.parent / rel)
                # 원본 이름에 한글이 있어(m01-01-fetch-답.svg) 서버 규칙(영숫자)에 맞게 <회차>-<번호>-<k> 로
                name = f"{rc}-{int(s['no']):02d}-{k}{pic.suffix.lower()}"
                if not pic.exists() or pic.suffix.lower() not in (".svg", ".png", ".jpg", ".webp"):
                    continue
                fdir.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(pic, fdir / name)
                md += f"\n\n![{alt}](img:{name})"
                if f"files/{name}" not in names:
                    names.append(f"files/{name}")
        s["markdown"] = md
    write_json(job.book / "solutions.json", sols)
    write_json(job.book / "images.json", names)
    if names:
        log(f"  해설 그림 {len(names)}장 — 이북 해설 칸에 함께")
    return len(names)


def run(job: Job, youtube_id: Optional[str] = None, version: Optional[str] = None, do_import: bool = True) -> Path:
    attach_figures(job)
    st = job.state()
    youtube_id = youtube_id or (st.get("posted") or {}).get("videoId")
    if not youtube_id:                       # 롱폼 공방에서 올렸으면 그 주소를 가져온다
        from .aside_export import posted_from_aside
        from .youtube import video_id
        rec = posted_from_aside(job)
        if rec:
            youtube_id = video_id(rec.get("url"))
            job.update_state(posted={**rec, "videoId": youtube_id, "via": "aside"})
            log(f"  롱폼 공방 업로드 기록 사용: {rec.get('url')}")
    if youtube_id:
        vm = video_map(job, youtube_id)
        write_json(job.book / "video_map.json", vm)
        log(f"s7 연동: 문항 {len(vm)}개 구간 · 판서 포인터 {sum(len(v['cues']) for v in vm)}개 · 영상 {youtube_id}")
    else:
        # 업로드 전 미리보기: 영상 구간 없이 교재(원문·채점·해설 글)만 먼저 게시
        (job.book / "video_map.json").unlink(missing_ok=True)
        log("s7 연동(미리보기): 유튜브 업로드 전이라 영상 구간 없이 교재만 게시합니다 — 업로드 후 다시 연동하세요")
    n = int(st.get("pkg_rev", 0)) + 1
    version = version or f"1.0.{n}"
    dist = ROOT / "content" / "dist"
    proc = subprocess.run([sys.executable, "-I", "-W", "ignore", str(ROOT / "tools/pipeline/package.py"), str(job.book),
                           "--version", version, "--out", str(dist)], capture_output=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(f"패키징 실패: {proc.stderr[-500:]}")
    pkg = dist / f"{job.book_id}-{version}.hsbpkg.zip"
    job.update_state(pkg_rev=n, package=str(pkg.relative_to(ROOT)).replace("\\", "/"))
    log(f"  패키지: {pkg.name}")
    if do_import:
        php = php_exe()
        if not php:
            log("  △ PHP 가 없어 로컬 서버 적재는 건너뜀 (setup.bat 이 tools/php 에 설치)")
        else:
            code = ("require 'src/bootstrap.php'; $r = Hsb\\Import\\import_package($argv[1]); "
                    "echo json_encode($r, JSON_UNESCAPED_UNICODE);")
            import os
            lan = ROOT / "server" / "config.lan.php"     # 로컬·랜 공유 서버가 쓰는 DB 에 적재
            env = dict(os.environ, **({"HSB_CONFIG": str(lan)} if lan.exists() else {}))
            r = subprocess.run([php, "-r", code, str(pkg.resolve())], cwd=ROOT / "server", capture_output=True,
                               encoding="utf-8", errors="replace", env=env)
            if r.returncode != 0:
                raise RuntimeError(f"서버 적재 실패: {(r.stderr or r.stdout)[-500:]}")
            log(f"  로컬 해설북에 게시: {r.stdout.strip()}")
    if youtube_id:
        job.mark("s7", version=version, youtubeId=youtube_id)
    else:
        job.update_state(preview_published=version)
    return pkg
