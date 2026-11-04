"""스튜디오 대시보드 (FastAPI, http://127.0.0.1:5300 — lan-run.bat 이면 사내 랜에도) — 롱폼 공방과 같은 틀

  ① 원문   _assets/index.json 의 회차(연도·책형) 목록, 원문·정답 파일
  ② 만들기 회차 표(대본·판서·음성·화면·영상·업로드·연동) + 고른 회차에 단계 실행(한 번에 하나, 차례로)
  ③ 결과 보기 회차 하나: 영상·썸네일·챕터·문항별 대본 편집·판서 화면
  ④ 음성 체크 문장별 실제 발음 보기·고치기·다시 합성 + 발음 사전(공통·과목) — studio/voicecheck.py
  ⑤ 올리기 유튜브 로그인·업로드(일부공개)·이북 연동
  /panel   올리기 사이드 패널 — 오른쪽 좁은 창(계정·회차·올리기·연동·로그), 왼쪽은 그 계정의 YouTube Studio Chrome
실행은 `python -m studio queue …` 하위 프로세스 하나(창을 닫아도 회차 폴더의 체크포인트가 남는다).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path
from typing import Any, Dict, List, Optional

from .. import JOBS, ROOT
from ..job import SUBJECT_IDS, Job, read_json, write_json

PORT = 5300
EBOOK_PORT = 5301                    # 「로컬 해설북 열기」를 누르면 이 포트에 완성작(이북 리더)을 띄운다
HOST = os.environ.get("HSB_STUDIO_HOST", "127.0.0.1")   # lan-run.bat 은 0.0.0.0 — 사내 랜의 다른 PC 에서도 대시보드
LOG = ROOT / "logs" / "studio.log"
_proc: Optional[subprocess.Popen] = None
_desc = ""
_lock = threading.Lock()


def _pid_alive(pid: int) -> bool:
    try:
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, encoding="mbcs", errors="replace",
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


def _series(name: str) -> Optional[Dict[str, Any]]:
    from ..job import mock_series
    return next((s for s in mock_series() if s["name"] == name), None)


def mock_rows(series: Dict[str, Any]) -> List[Dict[str, Any]]:
    """모의고사 표: 회차 × 과목(20문항) — 칸마다 영상 한 편·이북 한 권. 공개 범위는 교재(공개)/이북(일부공개)"""
    from ..job import mock_label, mock_parts
    out = []
    public, textbook = set(series.get("public") or []), set(series.get("textbook") or [])
    for n in series.get("rounds") or []:
        rc = f"m{n:02d}"
        try:
            parts = mock_parts(Path(series["book"]), rc)
        except FileNotFoundError:
            continue
        for p in parts:
            jid = f"{series['code']}-{rc}-p{p['part']}"
            rl, dest = mock_label(series, n), "교재" if n in textbook else "이북"
            r: Dict[str, Any] = {"key": jid, "id": jid, "year": f"{dest} {rl}", "booklet": p["subject"],
                                 "label": f"{dest} {rl} · {p['subject']} {p['range'][0]}~{p['range'][1]}번",
                                 "examDate": dest, "dest": dest,
                                 "files": [k for k in (MOCK_FILES["교재" if dest == "교재" else "이북"])
                                           if _mock_file(series, rc, k)],
                                 "exists": False}
            _status(r, jid)
            out.append(r)
    return out


# 회차 칸에서 바로 여는 파일 — 교재는 한글(.hwpx), 이북은 시험지. 이름 = 화면에 보이는 글자
MOCK_FILES = {"교재": ["교재 한권", "문제 한글", "해설 한글", "문제 PDF"], "이북": ["시험지", "문제 PDF"]}


def _mock_file(series: Dict[str, Any], rc: str, kind: str) -> Optional[Path]:
    """xam-local2 가 구운 07/ 산출물 — 정답·해설편은 그 회차가 든 answers_mAA-mBB.hwpx"""
    d = Path(series["book"]) / "07"
    if kind in ("해설 한글", "교재 한권"):         # 교재 한 권 = textbook_mAA-mBB (문제편 전부 + 정답·해설편)
        n = int(rc[1:])
        pat = "answers_m*-m*.hwpx" if kind == "해설 한글" else "textbook_m*-m*.hwpx"
        for f in sorted((d / "_textbook").glob(pat)):
            a, b = (int(x[1:]) for x in f.stem.split("_", 1)[1].split("-"))
            if a <= n <= b:
                return f
        return None
    p = d / rc / {"문제 한글": "exam.hwpx", "문제 PDF": "exam.pdf", "시험지": "exam.html"}.get(kind, "-")
    return p if p.is_file() else None


def _mock_pick(job_id: str, kind: str) -> Optional[tuple]:
    """(파일, 받을 이름) — 이 시리즈 회차가 아니거나 파일이 없으면 None"""
    from ..job import MOCK_ID, mock_label, mock_series
    m = MOCK_ID.match(job_id)
    series = next((e for e in mock_series() if m and e["code"] == m["code"]
                   and int(m["rc"][1:]) in (e.get("rounds") or [])), None)
    p = _mock_file(series, m["rc"], kind) if series else None
    if not p:
        return None
    n = int(m["rc"][1:])
    dest = "교재" if n in (series.get("textbook") or []) else "이북"
    if kind in ("해설 한글", "교재 한권"):         # answers_m01-m05 → 01~05회
        a, b = (int(x[1:]) for x in p.stem.split("_", 1)[1].split("-"))
        rl = f"{mock_label(series, a)[:-1]}~{mock_label(series, b)}"
        what = "정답해설" if kind == "해설 한글" else "문제+정답해설"
    else:
        rl, what = mock_label(series, n), "문제"
    return p, f"{series.get('short') or series['code']}_{dest} {rl}_{what}{p.suffix}"


def rows(subject: str) -> List[Dict[str, Any]]:
    """회차 표: _assets 의 모든 회차 + 작업 상태 (모의고사 시리즈 이름이면 회차×과목 표)"""
    series = _series(subject)
    if series:
        return mock_rows(series)
    out = []
    for e in read_json(ROOT / "_assets" / "index.json", []) or []:
        if e["subject"] != subject:
            continue
        for p in e["papers"]:
            jid = _job_id(e["year"], subject, p["booklet"], len(e["papers"]))
            r: Dict[str, Any] = {"key": f"{e['year']}|{p['booklet']}", "id": jid, "year": e["year"], "booklet": p["booklet"],
                                 "examDate": e.get("examDate"), "exists": False}
            _status(r, jid)
            out.append(r)
    return out


def _status(r: Dict[str, Any], jid: str) -> None:
    """작업이 있으면 단계별 상태를 행에 채운다"""
    d = JOBS / jid
    if not (d / "job.json").exists():
        return
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


def tools() -> Dict[str, Any]:
    from .. import claude
    from ..link import php_exe
    from ..tts import engine
    from .. import accounts
    prof = ROOT / "profiles" / accounts.current()
    return {
        "claude": claude.available(), "supertonic": not engine.missing(), "ffmpeg": bool(shutil.which("ffmpeg")),
        "php": bool(php_exe()), "chrome_profile": prof.exists() and any(prof.iterdir()),
    }


def create_app():
    from fastapi import Body, FastAPI, HTTPException
    from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, Response

    app = FastAPI(title="해설북 스튜디오")

    @app.get("/", response_class=HTMLResponse)
    def index():
        return (Path(__file__).parent / "index.html").read_text(encoding="utf-8")

    @app.get("/api/overview")
    def overview(subject: str = "컴퓨터일반"):
        from ..job import mock_series
        idx = read_json(ROOT / "_assets" / "index.json", []) or []
        subjects = (sorted({e["subject"] for e in idx}) or ["컴퓨터일반"]) + [s["name"] for s in mock_series()]
        rs = rows(subject)
        return {"subjects": subjects, "rows": rs, "running": running(), "tools": tools(),
                "totals": {
                    "rounds": len(rs), "script": sum(1 for r in rs if r.get("script") == 20),
                    "marks": sum(1 for r in rs if r.get("marksDone")),
                    "voice": sum(1 for r in rs if r.get("minutes")),
                    "video": sum(1 for r in rs if r.get("video")),
                    "minutes": round(sum(r.get("minutes") or 0 for r in rs if r.get("video"))),
                    "posted": sum(1 for r in rs if r.get("posted")),
                    "preview": sum(1 for r in rs if r.get("preview") or r.get("linked")),
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
            if body.get("account"):
                args += ["--account", str(body["account"])]
            if body.get("at"):
                args += ["--at", str(body["at"]).replace("T", " ")]
            if body.get("force"):
                args.append("--force")
            _proc = subprocess.Popen(args, cwd=ROOT, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            _desc = f"{', '.join(items)} · {' → '.join(stages)}"
        if "post" in stages:                 # 롱폼 공방처럼 — 왼쪽 YouTube Chrome, 오른쪽 올리기 패널
            threading.Thread(target=_panel, daemon=True).start()
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
    def login(body: Dict[str, Any] = Body(default={})):
        args = [sys.executable, "-m", "studio", "login"]
        if body.get("account"):
            args += ["--account", str(body["account"])]
        subprocess.Popen(args, cwd=ROOT, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        threading.Thread(target=_panel, daemon=True).start()
        return {"ok": True}

    # ── 계정(채널별 Chrome 프로필) · 올리기 패널 ──
    @app.get("/api/accounts")
    def accounts_list():
        from .. import accounts
        return {"accounts": accounts.all_(), "current": accounts.current()}

    @app.post("/api/accounts/use")
    def accounts_use(body: Dict[str, Any] = Body(...)):
        from .. import accounts
        try:
            accounts.set_current(str(body.get("name", "")))
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {"ok": True}

    @app.post("/api/accounts/add")
    def accounts_add(body: Dict[str, Any] = Body(...)):
        from .. import accounts
        try:
            acc = accounts.add(str(body.get("name", "")).strip(), str(body.get("label", "")))
        except ValueError as e:
            raise HTTPException(400, str(e))
        accounts.set_current(acc["name"])
        return acc

    @app.put("/api/accounts/{name}")
    def accounts_label(name: str, body: Dict[str, Any] = Body(...)):
        from .. import accounts
        accounts.set_label(name, str(body.get("label", "")))
        return {"ok": True}

    # ── 예약: 고른 회차를 시각 칸에 차례로 → Studio 「예약 공개」 + 이북 연동 ──
    @app.get("/api/plan")
    def plan_preview(items: str = "", pattern: str = "daily", start: str = "", time: str = "19:00", account: str = ""):
        from .. import schedule
        keys = [x for x in items.split(",") if x]
        when = schedule.slots(len(keys), pattern=pattern, start=start or None, at=time, account=account or None) if keys else []
        return {"patterns": {k: v["label"] for k, v in schedule.PATTERNS.items()}, "default": schedule.DEFAULT,
                "rows": [{"key": k, "when": w.strftime(schedule.FMT) if w else "", "dow": "월화수목금토일"[w.weekday()] if w else ""}
                         for k, w in zip(keys, when)],
                "taken": sorted(schedule.taken())}

    @app.post("/api/plan")
    def plan_apply(body: Dict[str, Any] = Body(...)):
        global _proc, _desc
        items: List[str] = body.get("items") or []
        if not items:
            raise HTTPException(400, "예약할 회차를 고르세요")
        with _lock:
            if running():
                raise HTTPException(409, f"이미 실행 중입니다: {_desc}")
            args = [sys.executable, "-m", "studio", "plan", "--items", ",".join(items), "--apply",
                    "--subject", body.get("subject", "컴퓨터일반"), "--pattern", body.get("pattern", "daily"),
                    "--time", body.get("time", "19:00"), "--visibility", body.get("visibility", "unlisted")]
            for k in ("start", "account"):
                if body.get(k):
                    args += [f"--{k}", str(body[k])]
            _proc = subprocess.Popen(args, cwd=ROOT, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            _desc = f"일괄 올리기 {len(items)}편"
        threading.Thread(target=_panel, daemon=True).start()
        return {"ok": True, "running": _desc}

    @app.get("/panel", response_class=HTMLResponse)
    def panel_page():
        return (Path(__file__).parent / "panel.html").read_text(encoding="utf-8")

    @app.post("/api/panel/open")
    def panel_open():
        return {"ok": _panel()}

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
        from ..job import record_mock_video
        record_mock_video(j, rec["url"])          # 모의고사면 교재 정답·해설편 QR 주소로도
        return rec

    @app.delete("/api/jobs/{job_id}/posted")
    def clear_posted(job_id: str):
        """잘못 올린 업로드 기록만 지운다(유튜브 영상은 그대로) — 이북은 다음 연동 때 미리보기로 돌아간다"""
        j = job_or_404(job_id)
        st = j.state()
        st.pop("posted", None)
        for k in ("s6", "s7"):
            (st.get("stages") or {}).pop(k, None)
        write_json(j.dir / "state.json", st)
        return {"ok": True}

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
        desc = ""
        if timing and script:
            from ..render import chapter_lines
            from ..youtube import description
            desc = description(script, chapter_lines(timing))
        return {"id": j.id, "title": j.meta["title"], "posted": st.get("posted"), "hasVideo": j.video.exists(),
                "description": desc, "tags": (script.get("youtube") or {}).get("tags") or [],
                "linked": ((st.get("stages") or {}).get("s7") or {}).get("youtubeId"), "preview": st.get("preview_published"),
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

    # ── ④ 음성 체크 · 발음 사전 ─────────────────────────────
    def vc(fn, *a):
        try:
            return fn(*a)
        except (KeyError, ValueError) as e:
            raise HTTPException(400, str(e))
        except (RuntimeError, ImportError) as e:      # 엔진·모델 없음 · Claude 실패
            raise HTTPException(503, str(e))

    @app.get("/api/jobs/{job_id}/voice")
    def voice_lines(job_id: str):
        from .. import voicecheck
        return vc(voicecheck.lines, job_or_404(job_id))

    @app.post("/api/jobs/{job_id}/voice/line")
    def voice_line(job_id: str, body: Dict[str, Any] = Body(...)):
        from .. import voicecheck
        return vc(voicecheck.save_line, job_or_404(job_id), str(body["id"]), str(body.get("tts", "")), bool(body.get("synth")))

    @app.post("/api/jobs/{job_id}/voice/ai")
    def voice_ai(job_id: str, body: Dict[str, Any] = Body(...)):
        from .. import voicecheck
        return {"suggest": vc(voicecheck.ai_fix, job_or_404(job_id), [str(i) for i in body.get("ids") or []], body.get("tts") or {})}

    @app.post("/api/jobs/{job_id}/voice/check")
    def voice_check(job_id: str, body: Dict[str, Any] = Body(...)):
        from .. import voicecheck
        return vc(voicecheck.check, job_or_404(job_id), str(body["id"]), str(body.get("tts", "")), bool(body.get("ok")))

    @app.post("/api/jobs/{job_id}/voice/ok")
    def voice_ok(job_id: str, body: Dict[str, Any] = Body(...)):
        job_or_404(job_id).update_state(voice_ok=True if body.get("ok") else None)
        return {"ok": True}

    @app.get("/api/jobs/{job_id}/voice/wav")
    def voice_wav(job_id: str, id: str):
        from .. import voicecheck
        p = vc(voicecheck.wav_of, job_or_404(job_id), id)
        if not p.exists():
            raise HTTPException(404, "아직 합성하지 않았습니다")
        return FileResponse(p, media_type="audio/wav")

    def dict_subject(subject: Optional[str], job: Optional[str]) -> Optional[str]:
        """모의고사 시리즈를 고른 상태면 사전은 그 작업의 과목(컴퓨터 일반·스프레드시트 일반) 것"""
        if subject and _series(subject):
            return job_or_404(job).meta["subject"] if job else None
        return subject

    @app.get("/api/dict")
    def dict_get(subject: str, job: Optional[str] = None):
        from .. import voicecheck
        return voicecheck.dict_list(dict_subject(subject, job), job_or_404(job) if job else None)

    @app.post("/api/dict")
    def dict_post(body: Dict[str, Any] = Body(...)):
        from .. import voicecheck
        return vc(voicecheck.dict_put, dict_subject(body.get("subject"), body.get("job")), str(body.get("k", "")), str(body.get("v", "")),
                  str(body.get("src", "과목")), bool(body.get("delete")))

    @app.post("/api/ebook/open")
    def ebook_open():
        """로컬 해설북(완성작 보기) — 안 떠 있으면 PHP 내장 서버를 EBOOK_PORT 에 띄운다"""
        if not _listening(EBOOK_PORT):
            from ..link import php_exe
            php, web = php_exe(), ROOT / "apps" / "web" / "dist" / "index.html"
            if not php or not web.exists():
                raise HTTPException(400, "PHP 나 웹앱 빌드가 없습니다 — setup.bat 을 먼저 실행하세요")
            lan = ROOT / "server" / "config.lan.php"
            env = dict(os.environ, **({"HSB_CONFIG": str(lan)} if lan.exists() else {}))
            bind = "0.0.0.0" if HOST == "0.0.0.0" else "127.0.0.1"
            subprocess.Popen([php, "-S", f"{bind}:{EBOOK_PORT}", "-t", str(web.parent),
                              str(ROOT / "server" / "public" / "lan-router.php")], cwd=ROOT, env=env,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            for _ in range(50):
                if _listening(EBOOK_PORT):
                    break
                time.sleep(0.1)
            else:
                raise HTTPException(500, f"로컬 해설북 서버가 {EBOOK_PORT} 포트에서 뜨지 않았습니다")
        return {"ok": True, "port": EBOOK_PORT}

    @app.post("/api/mock/hwpx")
    def mock_hwpx(body: Dict[str, Any] = Body(default={})):
        """「hwpx 생성」 — 교재 회차 문제편·정답해설편·교재 한 권. 진행은 아래 기록 창(studio.log)"""
        global _proc, _desc
        series = _series(str(body.get("subject", "")))
        if not series:
            raise HTTPException(400, "모의고사 시리즈를 고르세요")
        with _lock:
            if running():
                raise HTTPException(409, f"이미 실행 중입니다: {_desc}")
            LOG.parent.mkdir(parents=True, exist_ok=True)
            _proc = subprocess.Popen([sys.executable, "-m", "studio", "hwpx", "--code", series["code"]], cwd=ROOT,
                                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            _desc = f"{series['name']} · 교재 한글 만들기"
        return {"ok": True, "running": _desc}

    @app.post("/api/mock/folder")
    def mock_folder(body: Dict[str, Any] = Body(default={})):
        """교재 한글이 모인 07/_textbook 폴더를 탐색기로 연다 (회차별 문제편은 07/<mNN>/exam.hwpx)"""
        from ..job import mock_series
        series = _series(str(body.get("subject", ""))) or next(iter(mock_series()), None)
        d = Path(series["book"]) / "07" / "_textbook" if series else None   # 교재 한 권·정답해설편이 있는 곳
        if not d or not d.is_dir():
            raise HTTPException(404, "07 폴더가 없습니다 — xam-local2 「HTML 문제집 제작」에서 먼저 구우세요")
        os.startfile(str(d))  # type: ignore[attr-defined]
        return {"ok": True, "path": str(d)}

    @app.post("/api/mock/open")
    def mock_open(body: Dict[str, Any] = Body(...)):
        """회차 칸의 「문제 한글」 등 — 이 PC 에서 기본 프로그램(한글·브라우저)으로 연다"""
        from ..job import MOCK_ID, mock_series
        m = MOCK_ID.match(str(body.get("id", "")))
        series = next((e for e in mock_series() if m and e["code"] == m["code"]
                       and int(m["rc"][1:]) in (e.get("rounds") or [])), None)
        p = _mock_file(series, m["rc"], str(body.get("kind", ""))) if series else None
        if not p:
            raise HTTPException(404, "파일이 아직 없습니다 — xam-local2 「HTML 문제집 제작」에서 먼저 구우세요")
        os.startfile(str(p))  # type: ignore[attr-defined]
        return {"ok": True, "path": str(p)}

    @app.get("/api/mock/file/{job_id}/{kind}")
    def mock_download(job_id: str, kind: str):
        """회차 파일 하나 내려받기 — 이름은 「컴활 2급_교재 01회_문제.hwpx」처럼 알아보기 쉽게"""
        got = _mock_pick(job_id, kind)
        if not got:
            raise HTTPException(404, "파일이 아직 없습니다 — xam-local2 「HTML 문제집 제작」에서 먼저 구우세요")
        return FileResponse(got[0], filename=got[1])

    @app.get("/api/mock/bundle")
    def mock_bundle(ids: str, pdf: int = 0):
        """고른 회차들의 한글(+PDF)을 zip 하나로 — 과목 둘(p1·p2)이 같은 파일이면 한 번만, 해설편도 한 번만"""
        import io
        import zipfile
        kinds = ["문제 한글", "해설 한글"] + (["문제 PDF"] if pdf else [])
        seen: Dict[str, str] = {}
        for jid in [x for x in ids.split(",") if x]:
            for k in kinds:
                got = _mock_pick(jid, k)       # 교재 회차만 — 이북(6~10회)은 e-test 사이트가 07/ 에서 직접 가져간다
                if got and "_교재 " in got[1] and str(got[0]) not in seen:
                    seen[str(got[0])] = got[1]
        if not seen:
            raise HTTPException(404, "고른 회차에 받을 파일이 없습니다 (한글 파일은 교재 회차에만 있습니다)")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for src, name in sorted(seen.items(), key=lambda kv: kv[1]):
                z.write(src, name)
        short = next(iter(seen.values())).split("_", 1)[0]
        from urllib.parse import quote
        return Response(buf.getvalue(), media_type="application/zip", headers={
            "Content-Disposition": f"attachment; filename*=utf-8''{quote(f'{short}_교재 모아받기.zip')}"})

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


def _listening(port: int) -> bool:
    import socket
    with socket.socket() as sk:
        sk.settimeout(0.3)
        return sk.connect_ex(("127.0.0.1", port)) == 0


def _panel() -> bool:
    """올리기 패널을 오른쪽에 붙인다 — 보기 좋으라고 띄우는 것이라 실패해도 업로드는 계속"""
    from .. import youtube
    try:
        return youtube.open_panel(PORT)
    except BaseException as e:      # noqa: BLE001
        print(f"패널 열기 실패: {e}", flush=True)
        return False


def serve() -> None:
    import uvicorn
    JOBS.mkdir(parents=True, exist_ok=True)
    print("=" * 62)
    print(f"  해설북 스튜디오 대시보드:  http://127.0.0.1:{PORT}/")
    if HOST == "0.0.0.0":
        print("  [사내 랜] 다른 PC 에서:")
        for ip in _lan_ips():
            print(f"      http://{ip}:{PORT}/")
    print("  (브라우저가 안 열리면 위 주소를 직접 여세요)")
    print(f"  「로컬 해설북 열기」를 누르면 {EBOOK_PORT} 포트에 완성작 이북이 뜹니다")
    print("  이 창을 닫으면 대시보드가 꺼집니다." + ("" if HOST == "0.0.0.0" else " 랜 공유는 lan-run.bat"))
    print("=" * 62, flush=True)
    threading.Timer(1.2, lambda: webbrowser.open(f"http://127.0.0.1:{PORT}/")).start()
    uvicorn.run(create_app(), host=HOST, port=PORT, log_level="warning")


def _lan_ips() -> List[str]:
    import socket
    try:
        ips = {i[4][0] for i in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)}
    except OSError:
        ips = set()
    return sorted(ip for ip in ips if not ip.startswith(("127.", "169.254.")))
