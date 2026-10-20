"""스튜디오 대시보드 (FastAPI, http://127.0.0.1:5300) — 롱폼 공방과 같은 틀

  ① 원문   _assets/index.json 의 회차(연도·책형) 목록, 원문·정답 파일
  ② 만들기 회차 표(대본·판서·음성·화면·영상·업로드·연동) + 고른 회차에 단계 실행(한 번에 하나, 차례로)
  ③ 결과 보기 회차 하나: 영상·썸네일·챕터·문항별 대본 편집·판서 화면
  ④ 올리기 유튜브 로그인·업로드(일부공개)·이북 연동
실행은 `python -m studio queue …` 하위 프로세스 하나(창을 닫아도 회차 폴더의 체크포인트가 남는다).
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path
from typing import Any, Dict, List, Optional

from .. import JOBS, ROOT
from ..job import SUBJECT_IDS, Job, read_json, write_json

PORT = 5300
LOG = ROOT / "logs" / "studio.log"
_proc: Optional[subprocess.Popen] = None
_desc = ""
_lock = threading.Lock()


def _pid_alive(pid: int) -> bool:
    try:
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
        return str(pid) in out
    except Exception:
        return False


def running() -> Optional[str]:
    """이 대시보드가 띄운 작업, 또는 명령줄에서 시작한 대기열(logs/queue.json)"""
    if _proc and _proc.poll() is None:
        return _desc
    lock = ROOT / "logs" / "queue.json"
    info = read_json(lock)
    if info and _pid_alive(int(info.get("pid", 0))):
        return f"{info.get('desc', '')} (시작 {info.get('started', '')})"
    if info:
        lock.unlink(missing_ok=True)
    return None


def _job_id(year: int, subject: str, booklet: str, n_booklets: int) -> str:
    return f"{year}-g9-{SUBJECT_IDS.get(subject, 'subject')}" + (f"-{booklet}" if n_booklets > 1 else "")


def rows(subject: str) -> List[Dict[str, Any]]:
    """회차 표: _assets 의 모든 회차 + 작업 상태"""
    out = []
    for e in read_json(ROOT / "_assets" / "index.json", []) or []:
        if e["subject"] != subject:
            continue
        for p in e["papers"]:
            jid = _job_id(e["year"], subject, p["booklet"], len(e["papers"]))
            r: Dict[str, Any] = {"key": f"{e['year']}|{p['booklet']}", "id": jid, "year": e["year"], "booklet": p["booklet"],
                                 "examDate": e.get("examDate"), "exists": False}
            d = JOBS / jid
            if (d / "job.json").exists():
                j = Job(jid)
                st = j.state()
                stages = st.get("stages") or {}
                timing = read_json(j.audio / "timing.json") or {}
                n_script = len(list(j.scripts.glob("q??.json"))) if j.scripts.exists() else 0
                n_marks = 0
                if j.scripts.exists():
                    for f in j.scripts.glob("q??.marks.json"):
                        n_marks += len((read_json(f) or {}).get("marks", []))
                r.update({
                    "exists": True, "title": j.meta["title"], "s0": bool(stages.get("s0", {}).get("done")),
                    "script": n_script, "marks": n_marks, "marksDone": bool(stages.get("s2", {}).get("done")),
                    "minutes": round(timing.get("duration", 0) / 60, 1) if stages.get("s3") else None,
                    "frames": (stages.get("s4") or {}).get("frames"),
                    "video": j.video.exists(), "mb": (stages.get("s5") or {}).get("mb"),
                    "posted": st.get("posted"), "linked": (stages.get("s7") or {}).get("youtubeId"),
                    "preview": st.get("preview_published"), "waiting": st.get("waiting"),
                })
            out.append(r)
    return out


def tools() -> Dict[str, Any]:
    from .. import claude
    from ..link import php_exe
    from ..tts import engine
    prof = ROOT / "profiles" / "dekman"
    return {
        "claude": claude.available(), "supertonic": not engine.missing(), "ffmpeg": bool(shutil.which("ffmpeg")),
        "php": bool(php_exe()), "chrome_profile": prof.exists() and any(prof.iterdir()),
    }


def create_app():
    from fastapi import Body, FastAPI, HTTPException
    from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse

    app = FastAPI(title="해설북 스튜디오")

    @app.get("/", response_class=HTMLResponse)
    def index():
        return (Path(__file__).parent / "index.html").read_text(encoding="utf-8")

    @app.get("/api/overview")
    def overview(subject: str = "컴퓨터일반"):
        idx = read_json(ROOT / "_assets" / "index.json", []) or []
        subjects = sorted({e["subject"] for e in idx}) or ["컴퓨터일반"]
        rs = rows(subject)
        return {"subjects": subjects, "rows": rs, "running": running(), "tools": tools(),
                "totals": {
                    "rounds": len(rs), "script": sum(1 for r in rs if r.get("script") == 20),
                    "marks": sum(1 for r in rs if r.get("marksDone")),
                    "voice": sum(1 for r in rs if r.get("minutes")),
                    "video": sum(1 for r in rs if r.get("video")),
                    "minutes": round(sum(r.get("minutes") or 0 for r in rs if r.get("video"))),
                    "posted": sum(1 for r in rs if r.get("posted")),
                    "linked": sum(1 for r in rs if r.get("linked")),
                }}

    @app.post("/api/run")
    def run(body: Dict[str, Any] = Body(...)):
        global _proc, _desc
        items: List[str] = body.get("items") or []
        stages: List[str] = body.get("stages") or []
        ok = {"s0", "s1", "s2", "s3", "s4", "s5", "post", "link", "aside"}
        if not items or not stages or any(s not in ok for s in stages):
            raise HTTPException(400, "회차와 단계를 고르세요")
        with _lock:
            if running():
                raise HTTPException(409, f"이미 실행 중입니다: {_desc}")
            LOG.parent.mkdir(parents=True, exist_ok=True)
            args = [sys.executable, "-m", "studio", "queue", "--items", ",".join(items), "--stages", ",".join(stages),
                    "--subject", body.get("subject", "컴퓨터일반"), "--visibility", body.get("visibility", "unlisted")]
            if body.get("force"):
                args.append("--force")
            _proc = subprocess.Popen(args, cwd=ROOT, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            _desc = f"{', '.join(items)} · {' → '.join(stages)}"
        return {"ok": True, "running": _desc}

    @app.post("/api/stop")
    def stop():
        if _proc and _proc.poll() is None:
            subprocess.run(["taskkill", "/PID", str(_proc.pid), "/T", "/F"], capture_output=True)
        else:
            info = read_json(ROOT / "logs" / "queue.json")
            if info and info.get("pid"):
                subprocess.run(["taskkill", "/PID", str(info["pid"]), "/T", "/F"], capture_output=True)
                (ROOT / "logs" / "queue.json").unlink(missing_ok=True)
        return {"ok": True}

    @app.post("/api/login")
    def login():
        subprocess.Popen([sys.executable, "-m", "studio", "login"], cwd=ROOT,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return {"ok": True}

    @app.post("/api/jobs/{job_id}/posted")
    def set_posted(job_id: str, body: Dict[str, Any] = Body(...)):
        """직접 올린 영상 주소를 붙여 넣기 → 이북 연동이 이 영상을 쓴다"""
        from datetime import datetime
        from ..youtube import video_id, watch_url
        j = job_or_404(job_id)
        url = str(body.get("url", "")).strip()
        vid = video_id(url) or (url if len(url) == 11 else None)
        if not vid:
            raise HTTPException(400, "유튜브 주소를 알아볼 수 없습니다 (예: https://youtu.be/xxxxxxxxxxx)")
        rec = {"url": watch_url(f"https://youtu.be/{vid}"), "videoId": vid, "visibility": body.get("visibility", "unlisted"),
               "via": "manual", "at": datetime.now().isoformat(timespec="seconds")}
        j.update_state(posted=rec)
        return rec

    @app.get("/api/log", response_class=PlainTextResponse)
    def log_tail():
        if not LOG.exists():
            return ""
        return "\n".join(LOG.read_text(encoding="utf-8", errors="replace").splitlines()[-300:])

    def job_or_404(job_id: str) -> Job:
        try:
            return Job(job_id)
        except FileNotFoundError:
            raise HTTPException(404, "아직 만들지 않은 회차입니다")

    @app.get("/api/jobs/{job_id}")
    def detail(job_id: str):
        j = job_or_404(job_id)
        script = j.script() or {}
        quizzes = []
        for ch in script.get("chapters", []):
            if ch.get("kind") == "quiz":
                no = ch["quiz"]
                q = read_json(j.scripts / f"q{no:02d}.json") or {}
                mk = (read_json(j.scripts / f"q{no:02d}.marks.json") or {}).get("marks", [])
                quizzes.append({"no": no, "title": ch["title"], "answers": q.get("answers"),
                                "lines": {k: q.get(k, []) for k in ("read", "solve", "answer")}, "marks": len(mk)})
        timing = read_json(j.audio / "timing.json") or {}
        st = j.state()
        return {"id": j.id, "title": j.meta["title"], "posted": st.get("posted"), "hasVideo": j.video.exists(),
                "hasThumb": j.thumb.exists(), "quizzes": quizzes, "duration": timing.get("duration"),
                "chapters": [{"title": c["title"], "start": c["start"]} for c in timing.get("chapters", [])],
                "youtube": (script.get("youtube") or {})}

    @app.put("/api/jobs/{job_id}/quiz/{no}")
    def save_quiz(job_id: str, no: int, body: Dict[str, Any] = Body(...)):
        """문항 대본 편집 → script/qNN.json + script.json 재조립 (목소리·화면은 바뀐 문장만 다시)"""
        from ..script import assemble
        j = job_or_404(job_id)
        path = j.scripts / f"q{no:02d}.json"
        q = read_json(path)
        if not q:
            raise HTTPException(404, "대본이 없습니다")
        for k in ("read", "solve", "answer"):
            if k in body["lines"]:
                q[k] = [{"say": str(x.get("say", "")).strip(), "cap": str(x.get("cap", "")).strip()}
                        for x in body["lines"][k] if str(x.get("say", "")).strip()]
        write_json(path, q)
        items = {qq["no"]: read_json(j.scripts / f"q{qq['no']:02d}.json") for qq in read_json(j.book / "questions.json", [])}
        write_json(j.dir / "script.json", assemble(j, items))
        (j.dir / "script.edit.json").unlink(missing_ok=True)
        return {"ok": True}

    @app.get("/api/jobs/{job_id}/file/{kind}")
    def file(job_id: str, kind: str, no: Optional[int] = None):
        j = job_or_404(job_id)
        p: Optional[Path] = None
        if kind == "video":
            p = j.video
        elif kind == "thumb":
            p = j.thumb
        elif kind == "contact":
            p = j.out / f"contact_{(no or 1):02d}.jpg"
        elif kind == "frame" and no:
            frames = read_json(j.boards / "frames.json") or []
            timing = read_json(j.audio / "timing.json") or {}
            chs = timing.get("chapters", [])
            ch = next((c for c in chs if c.get("quiz") == no), None)
            if ch:
                nxt = next((c["start"] for c in chs if c["start"] > ch["start"]), 1e9)
                cands = [f for f in frames if ch["start"] <= f["start"] < nxt]
                if cands:
                    p = j.boards / cands[-1]["img"]
            p = p or j.boards / f"crop/q{no:02d}.png"
        elif kind == "paper":
            p = j.paper
        if not p or not p.exists():
            raise HTTPException(404)
        return FileResponse(p)

    return app


def serve() -> None:
    import uvicorn
    JOBS.mkdir(parents=True, exist_ok=True)
    print("=" * 62)
    print(f"  해설북 스튜디오 대시보드:  http://127.0.0.1:{PORT}/")
    print("  (브라우저가 안 열리면 위 주소를 직접 여세요)")
    print("  이 창을 닫으면 대시보드가 꺼집니다. 이북 공유는 lan-run.bat")
    print("=" * 62, flush=True)
    threading.Timer(1.2, lambda: webbrowser.open(f"http://127.0.0.1:{PORT}/")).start()
    uvicorn.run(create_app(), host="127.0.0.1", port=PORT, log_level="warning")
