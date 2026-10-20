"""해설북 스튜디오 명령 — run.bat <명령> 또는 python -m studio <명령>

  new --year 2025 [--subject 컴퓨터일반]     작업 만들기 (_assets/index.json 기준)
  make --job ID                              s0 원문 → s1 대본 → s2 판서 → s3 목소리 → s4 화면 → s5 영상·썸네일
  batch --years 2018-2025                    여러 해를 차례로 make (끝난 단계는 건너뜀 · 한도 소진 시 기다렸다 이어서)
  s0 | s1 | s2 | s3 | s4 | s5 --job ID [--force] [--only 3,7]
  post --job ID [--visibility unlisted] [--dry-run]   유튜브 업로드 (기본 일부공개)
  link --job ID [--youtube VIDEOID]          이북 연동: video_map + 패키지 + 로컬 서버 적재
  login                                      유튜브 로그인용 Chrome 열기 (처음 한 번)
  tts-setup · doctor · ui
같은 명령을 다시 실행하면 끝난 문항·문장·화면은 저장본을 쓴다(중단·한도 소진 후 이어서 시작).
"""
from __future__ import annotations

import argparse
import shutil
import sys
import traceback
from typing import List, Optional

from . import ROOT
from .log import log, to_file

STAGES = ["s0", "s1", "s2", "s3", "s4", "s5"]
STAGE_NAMES = {"s0": "원문·정답·크롭", "s1": "대본(Claude)", "s2": "판서 계획(Claude)", "s3": "목소리(F1)",
               "s4": "판서 화면", "s5": "영상·썸네일", "s6": "유튜브 업로드", "s7": "이북 연동"}


def _only(s: Optional[str]) -> Optional[List[int]]:
    return [int(x) for x in s.split(",") if x.strip()] if s else None


def run_stage(job, stage: str, force: bool = False, only: Optional[List[int]] = None) -> None:
    from . import boards, frames, marks, prepare, render, script, thumb, voice
    log(f"── {job.id} · {stage} {STAGE_NAMES[stage]}")
    if stage == "s0":
        prepare.run(job, force)
    elif stage == "s1":
        script.run(job, force, only)
    elif stage == "s2":
        marks.run(job, force, only)
    elif stage == "s3":
        voice.run(job, force)
    elif stage == "s4":
        frames.run(job, force)
    elif stage == "s5":
        render.run(job, force)
        thumb.run(job, force)


def make(job, force: bool = False) -> None:
    to_file(job.dir / "log.txt")
    for st in STAGES:
        run_stage(job, st, force)
    log(f"✓ {job.id} 영상 완성: {job.video}")


def _years(spec: str) -> List[int]:
    out: List[int] = []
    for part in spec.split(","):
        a, _, b = part.partition("-")
        out += list(range(int(a), int(b or a) + 1))
    return out


def doctor() -> int:
    from . import claude, youtube
    from .link import php_exe
    from .tts import engine
    ok = True
    def row(name, good, hint=""):
        nonlocal ok
        ok = ok and good
        log(f"  {'✓' if good else '✗'} {name}" + ("" if good else f" — {hint}"))
    log("점검")
    row("ffmpeg", bool(shutil.which("ffmpeg")), "winget install Gyan.FFmpeg")
    row("claude CLI", claude.available(), "Claude Code 설치 후 claude auth login")
    row("SuperTonic3 모델", not engine.missing(), "setup.bat (또는 python -m studio tts-setup)")
    try:
        youtube.chrome_path()
        row("Google Chrome", True)
    except Exception as e:
        row("Google Chrome", False, str(e))
    row("PHP (로컬 해설북 서버)", bool(php_exe()), "setup.bat 이 tools/php 에 설치")
    row("_assets/index.json", (ROOT / "_assets" / "index.json").exists(), "_assets 정리 필요")
    return 0 if ok else 1


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="studio", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("new")
    p.add_argument("--year", type=int, required=True)
    p.add_argument("--subject", default="컴퓨터일반")
    p.add_argument("--booklet")
    for name in ["make", *STAGES]:
        p = sub.add_parser(name)
        p.add_argument("--job", required=True)
        p.add_argument("--force", action="store_true")
        p.add_argument("--only")
    p = sub.add_parser("batch")
    p.add_argument("--years", required=True, help="예: 2018-2025 또는 2023,2025")
    p.add_argument("--subject", default="컴퓨터일반")
    p.add_argument("--post", action="store_true", help="영상마다 일부공개 업로드 + 이북 연동까지")
    p = sub.add_parser("queue", help="고른 회차들에 단계들을 차례로 (대시보드가 부름)")
    p.add_argument("--items", required=True, help="연도|책형 쉼표 목록 예: 2025|나,2019|라")
    p.add_argument("--stages", required=True, help="예: s0,s1,s2 또는 post 또는 link")
    p.add_argument("--subject", default="컴퓨터일반")
    p.add_argument("--force", action="store_true")
    p.add_argument("--visibility", default="unlisted")
    p = sub.add_parser("post")
    p.add_argument("--job", required=True)
    p.add_argument("--visibility", default="unlisted", choices=["unlisted", "public", "private"])
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--force", action="store_true")
    p = sub.add_parser("link")
    p.add_argument("--job", required=True)
    p.add_argument("--youtube")
    p.add_argument("--no-import", action="store_true")
    p = sub.add_parser("export-aside", help="완성 영상을 롱폼 공방 작업 폴더로 내보내기(공방에서 업로드)")
    p.add_argument("--job", required=True)
    p.add_argument("--to", help="롱폼 공방 폴더 (기본: 환경변수 HSB_ASIDE_DIR 또는 D:\00work\261011-롱폼 세계사)")
    for name in ("login", "tts-setup", "doctor", "ui"):
        sub.add_parser(name)
    a = ap.parse_args(argv)

    from .job import Job, create
    try:
        if a.cmd == "new":
            j = create(a.year, a.subject, booklet=a.booklet)
            log(f"작업: {j.id}  ({j.paper.name})")
        elif a.cmd == "make":
            make(Job(a.job), a.force)
        elif a.cmd in STAGES:
            j = Job(a.job)
            to_file(j.dir / "log.txt")
            run_stage(j, a.cmd, a.force, _only(a.only))
        elif a.cmd == "batch":
            failed = []
            for y in _years(a.years):
                try:
                    j = create(y, a.subject)
                    make(j)
                    if a.post:
                        post(j, "unlisted")
                        from . import link
                        link.run(j)
                except Exception as e:     # 한 해가 실패해도 나머지는 계속
                    failed.append((y, str(e)[:200]))
                    log(f"✗ {y} 실패: {e}")
            log("일괄 끝" + (f" — 실패: {failed}" if failed else " — 모두 성공"))
            return 1 if failed else 0
        elif a.cmd == "queue":
            to_file(ROOT / "logs" / "studio.log")
            stages = [s for s in a.stages.split(",") if s]
            import json as _json, os as _os, time as _time
            lock = ROOT / "logs" / "queue.json"   # 대시보드가 「실행 중」으로 알아보게(대시보드 밖에서 시작해도)
            lock.write_text(_json.dumps({"pid": _os.getpid(), "desc": f"{a.items} · {' → '.join(stages)}",
                                         "started": _time.strftime("%H:%M")}, ensure_ascii=False), encoding="utf-8")
            failed = []
            for item in [x for x in a.items.split(",") if x]:
                year, _, booklet = item.partition("|")
                try:
                    j = create(int(year), a.subject, booklet=booklet or None)
                    for st in stages:
                        if st in STAGES:
                            run_stage(j, st, a.force)
                        elif st == "post":
                            post(j, a.visibility, force=a.force)
                        elif st == "link":
                            from . import link
                            link.run(j)
                        elif st == "aside":
                            from . import aside_export
                            aside_export.export(j)
                    to_file(ROOT / "logs" / "studio.log")
                    log(f"✓ {j.id} — {', '.join(stages)} 끝")
                except Exception as e:      # 한 회차가 실패해도 다음 회차는 계속
                    to_file(ROOT / "logs" / "studio.log")
                    failed.append(item)
                    log(f"✗ {item} 실패: {e}")
            log("대기열 끝" + (f" — 실패: {failed}" if failed else ""))
            lock.unlink(missing_ok=True)
            return 1 if failed else 0
        elif a.cmd == "post":
            post(Job(a.job), a.visibility, a.dry_run, a.force)
        elif a.cmd == "link":
            from . import link
            j = Job(a.job)
            to_file(j.dir / "log.txt")
            link.run(j, a.youtube, do_import=not a.no_import)
        elif a.cmd == "export-aside":
            from . import aside_export
            aside_export.export(Job(a.job), a.to)
        elif a.cmd == "login":
            from . import youtube
            youtube.open_login()
        elif a.cmd == "tts-setup":
            from .tts import engine
            engine.download(log)
            log("SuperTonic3 준비 완료" if not engine.missing() else f"누락: {engine.missing()}")
        elif a.cmd == "doctor":
            return doctor()
        elif a.cmd == "ui":
            from .web import serve
            serve()
        else:
            ap.print_help()
        return 0
    except KeyboardInterrupt:
        log("중단 — 같은 명령을 다시 실행하면 이어서 합니다")
        return 130
    except Exception as e:
        log(f"오류: {e}")
        (ROOT / "logs").mkdir(exist_ok=True)
        (ROOT / "logs" / "last-error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        return 1


def post(job, visibility: str = "unlisted", dry_run: bool = False, force: bool = False) -> None:
    from . import youtube
    from .job import read_json
    from .render import chapter_lines
    to_file(job.dir / "log.txt")
    st = job.state()
    if st.get("posted") and not force and not dry_run:
        log(f"이미 올렸습니다: {st['posted'].get('url')} (다시 올리려면 --force)")
        return
    if not job.video.exists():
        raise RuntimeError("영상이 없습니다 — make 를 먼저")
    log(f"── {job.id} · s6 유튜브 업로드 ({visibility})")
    chapters = chapter_lines(read_json(job.audio / "timing.json"))
    playlist = job.setting("playlist") or f"{job.meta['exam']} {job.meta['subject']} 기출 해설"
    log(f"  재생목록: {playlist}")
    rec = youtube.upload(job.script(), job.video, chapters=chapters, thumb=job.thumb, visibility=visibility,
                         dry_run=dry_run, playlist=playlist)
    if not dry_run:
        job.update_state(posted=rec)
        job.mark("s6", url=rec.get("url"))
