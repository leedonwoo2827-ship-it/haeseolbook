"""롱폼 공방(aside-long)으로 내보내기 — 공방의 「④ 올리기」(로그인·채널·예약이 이미 갖춰진 곳)에서 업로드하고 싶을 때.

이 저장소는 공방에 의존하지 않는다. 완성된 영상을 공방의 작업 폴더 형식으로 **복사해 넣을 뿐**이다.
  <공방>/jobs/<시리즈>/job.json                       시리즈 이름·목소리·재생목록
  <공방>/jobs/<시리즈>/<연도>-1_<제목>/unit.json       단원 제목
      03_script/<sid>.json   대본(장·씬·문장) + youtube 문구 + 썸네일 문구
      04_bundle/audio/       timing.json(챕터) · narration.wav
      04_bundle/out/         <sid>.mp4 · <sid>_thumb.jpg
공방에서 올리면 공방의 state.json 에 주소가 남고, `link` 가 그것을 읽어 이북에 연동한다(posted_from_aside).
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any, Dict, Optional

from .job import Job, read_json, write_json
from .log import log

DEFAULT_DIR = Path(os.environ.get("HSB_ASIDE_DIR", r"D:\00work\261011-롱폼 세계사"))


def series_name(job: Job) -> str:
    return f"{job.meta['exam'].replace(' ', '')}-{job.meta['subject']}"


def sid(job: Job) -> str:
    return f"{job.meta['year']}-1"


def _link(src: Path, dst: Path) -> None:
    """같은 드라이브면 하드링크(디스크 절약), 아니면 복사"""
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        dst.unlink()
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def export(job: Job, aside_dir: Optional[Path] = None) -> Path:
    aside = Path(aside_dir or DEFAULT_DIR)
    if not (aside / "aside_long").exists():
        raise RuntimeError(f"롱폼 공방 폴더가 아닙니다: {aside} (--to 로 지정)")
    if not job.video.exists():
        raise RuntimeError("영상이 없습니다 — 먼저 만들기(0→5)")
    script = job.script()
    timing = read_json(job.audio / "timing.json")
    series = aside / "jobs" / series_name(job)
    if not (series / "job.json").exists():
        write_json(series / "job.json", {
            "title": f"{job.meta['exam']} {job.meta['subject']} 기출 해설",
            "long": {"plan_confirmed": True, "style": "textbook"},
            "tts": {"voice": job.setting("voice", "F1"), "speed": 1.0},
            "youtube": {"playlist": f"{job.meta['exam']} {job.meta['subject']} 기출 해설"},
        })
    s = sid(job)
    title = job.meta["title"]
    unit = series / f"{s}_{title}"[:60]
    for old in series.glob(f"{s}_*"):           # 제목이 바뀌었으면 옛 폴더 이름 정리
        if old != unit and old.is_dir():
            old.rename(unit)
    from . import ROOT
    # root·job: 공방이 「이북 연동」을 해설북에 대신 시킬 때 쓴다
    write_json(unit / "unit.json", {"title": title, "from": "haeseolbook", "job": job.id, "root": str(ROOT)})
    yt = dict(script.get("youtube") or {})
    yt.setdefault("desc_tags", (yt.get("tags") or [])[:3])
    yt.setdefault("pinned_comment", "문항별 챕터로 원하는 문항부터 보세요. 원문 위에 직접 풀어 보려면 해설북(이북)에서!")
    aside_script = {
        "id": s, "unit": s, "title": title, "topic": title,
        "chapters": [{"title": ch["title"], "scenes": [{"image": {"prompt": "", "chars": []}, "lines": sc["lines"]}
                                                       for sc in ch["scenes"]]} for ch in script["chapters"]],
        "characters": [], "thumbnail": script.get("thumbnail") or {}, "youtube": yt,
    }
    write_json(unit / "03_script" / f"{s}.json", aside_script)
    write_json(unit / "04_bundle" / "audio" / "timing.json", timing)
    _link(job.audio / "narration.wav", unit / "04_bundle" / "audio" / "narration.wav")
    _link(job.video, unit / "04_bundle" / "out" / f"{s}.mp4")
    if job.thumb.exists():
        _link(job.thumb, unit / "04_bundle" / "out" / f"{s}_thumb.jpg")
    job.update_state(aside={"dir": str(aside), "series": series.name, "sid": s})
    log(f"롱폼 공방으로 내보냄: {series.name} / {unit.name}  → 공방 「④ 올리기」에서 올리세요")
    return unit


def posted_from_aside(job: Job) -> Optional[Dict[str, Any]]:
    """공방에서 올렸으면 그 기록({url, …})"""
    info = job.state().get("aside")
    if not info:
        return None
    st = read_json(Path(info["dir"]) / "jobs" / info["series"] / "state.json", {}) or {}
    rec = (st.get(info["sid"]) or {}).get("posted")
    return rec if rec and rec.get("url") else None
