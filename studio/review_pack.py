"""검수 파일 — 회사 PC 에서 굽고, 집 노트북에서 브라우저만으로 검수한다.

  out/<id>_검수.html        5 영상이 끝나면 mp4 옆에 생긴다(줄 문장·시각이 파일 안에 들어 있다. 서버·설치 없음)
  <드라이브>/<id>/          mp4 + 검수.html 을 복사 — 집에서 「검수표 저장」한 <id>_검수표.json 을 여기 두면
                            음성 체크 탭 「드라이브에서 불러오기」가 가져온다
  드라이브 폴더: 환경변수 HSB_REVIEW_DIR, 없으면 G:/내 드라이브/해설북 검수 (Google Drive 데스크톱)
검수표 json: {"job": id, "made": ..., "saved": ..., "marks": [{"id": "L058", "t": 662.4, "say": "이렇게 읽기", "note": "메모"}]}
"""
from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .job import Job
from .log import log

TEMPLATE = Path(__file__).parent / "web" / "review.html"


def drive_dir() -> Optional[Path]:
    env = os.environ.get("HSB_REVIEW_DIR")
    if env:
        return Path(env)
    for root in (Path("G:/내 드라이브"), Path("G:/My Drive")):
        if root.is_dir():
            return root / "해설북 검수"
    return None


def html_path(job: Job) -> Path:
    return job.out / f"{job.id}_검수.html"


def payload(job: Job) -> Dict[str, Any]:
    from . import voicecheck
    v = voicecheck.lines(job)
    lines = [{"id": ln["id"], "cap": ln["cap"], "tts": ln["tts"]} for ch in v["chapters"] for ln in ch["lines"]]
    return {"job": job.id, "title": job.meta.get("title", job.id), "video": job.video.name,
            "made": time.strftime("%Y-%m-%d %H:%M"), "cues": v["cues"], "lines": lines}


def make(job: Job, copy: bool = True) -> Dict[str, Any]:
    """검수 HTML 을 만들고(있으면 새로) 드라이브 폴더로 mp4 와 함께 복사"""
    if not job.video.exists():
        raise ValueError("아직 구운 영상이 없습니다")
    data = json.dumps(payload(job), ensure_ascii=False).replace("</", "<\\/")
    html = TEMPLATE.read_text(encoding="utf-8").replace("/*__DATA__*/null", data, 1)
    out = html_path(job)
    out.write_text(html, encoding="utf-8")
    res: Dict[str, Any] = {"ok": True, "html": str(out), "drive": None}
    d = drive_dir()
    if copy and d:
        dd = d / job.id
        dd.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(out, dd / out.name)
        dst = dd / job.video.name
        st = job.video.stat()
        if not dst.exists() or dst.stat().st_size != st.st_size or dst.stat().st_mtime < st.st_mtime:
            shutil.copy2(job.video, dst)                    # 같은 판이면 다시 올리지 않는다
        res["drive"] = str(dd)
    log(f"검수 파일: {out.name}" + (f" → 드라이브 {res['drive']}" if res["drive"] else " (드라이브 폴더 없음 — out/ 에만)"))
    return res


def safe_make(job: Job) -> None:
    """5 영상 끝에 붙여 부른다 — 실패해도 영상 생산은 멈추지 않는다"""
    try:
        make(job)
    except Exception as e:  # noqa: BLE001
        log(f"검수 파일 건너뜀: {e}")


def results(job: Job) -> List[Path]:
    """집에서 저장한 검수표 json — 드라이브 회차 폴더·out/ 에서, 새것부터"""
    found: List[Path] = []
    d = drive_dir()
    for folder in ([d / job.id] if d else []) + [job.out]:
        if folder.is_dir():
            found += [p for p in folder.glob(f"{job.id}_검수표*.json")]
    return sorted(found, key=lambda p: p.stat().st_mtime, reverse=True)


def import_result(job: Job, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """검수표 json 을 이 회차 검수표에 합친다 — 표시는 합치고, 「이렇게 읽기」는 그 줄 낭독 칸에 넣는다(합성은 안 함)"""
    from . import voicecheck
    src = "보낸 파일"
    if data is None:
        files = results(job)
        if not files:
            raise ValueError(f"드라이브에 {job.id}_검수표.json 이 없습니다" + (f" ({drive_dir() / job.id})" if drive_dir() else ""))
        data, src = json.loads(files[0].read_text(encoding="utf-8")), files[0].name
    if data.get("job") and data["job"] != job.id:
        raise ValueError(f"다른 회차의 검수표입니다: {data['job']}")
    have = {m["id"]: m for m in voicecheck.review_get(job)}
    said = 0
    for m in data.get("marks") or []:
        mid = str(m.get("id", ""))
        cur = have.get(mid, {"id": mid, "t": m.get("t", 0)})
        for k in ("say", "note"):
            if str(m.get(k) or "").strip():
                cur[k] = str(m[k]).strip()
        have[mid] = cur
        if str(m.get("say") or "").strip():
            try:
                voicecheck.save_line(job, mid, str(m["say"]))
                said += 1
            except KeyError:                                 # 그새 대본이 바뀌어 없어진 줄
                pass
    marks = sorted(have.values(), key=lambda m: float(m.get("t", 0)))
    r = voicecheck.review_put(job, marks)
    return {"ok": True, "from": src, "marks": len(r["marks"]), "said": said}
