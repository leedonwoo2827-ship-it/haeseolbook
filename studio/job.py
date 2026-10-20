"""작업(job) = 시험지 한 회차 = 영상 한 편 = 이북 교재 한 권.

studio/jobs/<id>/
  job.json          {id, year, subject, booklet, exam, title, paper, answers, voice, speed, model}
  state.json        {stages: {s0: {...}, ...}, posted: {url, at, visibility}, waiting: {...}}
  log.txt           진행 로그 (대시보드가 읽는다)
  book/             이북 빌드 (pages, regions.json, questions.json, quizzes.json, solutions.json, video_map.json)
  boards/           문제판 이미지 (qNN_read.png, qNN_answer.png, intro.png, outro.png) + boards.json
  script/qNN.json   문항별 대본 체크포인트 (한도 소진 후 이어서 시작하는 지점)
  script.json       전체 대본 · script.edit.json (대시보드에서 고친 것, 언제나 우선)
  audio/            lines/<hash>.wav, narration.wav, timing.json
  out/              <id>.mp4, <id>_thumb.jpg, contact_NN.jpg, chapters.txt
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import JOBS, ROOT

_lock = threading.Lock()

SUBJECT_IDS = {"컴퓨터일반": "computer", "정보보호론": "infosec", "국어": "korean", "영어": "english", "한국사": "history"}


def read_json(p: Path, default: Any = None) -> Any:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def write_json(p: Path, data: Any) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)


class Job:
    def __init__(self, job_id: str):
        self.id = job_id
        self.dir = JOBS / job_id
        if not (self.dir / "job.json").exists():
            raise FileNotFoundError(f"작업이 없습니다: {job_id} (python -m studio new --year …)")
        self.meta: Dict[str, Any] = read_json(self.dir / "job.json")

    # ── 경로 ─────────────────────────────────────
    @property
    def book(self) -> Path: return self.dir / "book"
    @property
    def boards(self) -> Path: return self.dir / "boards"
    @property
    def scripts(self) -> Path: return self.dir / "script"
    @property
    def audio(self) -> Path: return self.dir / "audio"
    @property
    def out(self) -> Path: return self.dir / "out"
    @property
    def video(self) -> Path: return self.out / f"{self.id}.mp4"
    @property
    def thumb(self) -> Path: return self.out / f"{self.id}_thumb.jpg"
    @property
    def paper(self) -> Path: return ROOT / self.meta["paper"]
    @property
    def answers_pdf(self) -> Path: return ROOT / self.meta["answers"]

    def setting(self, key: str, default: Any = None) -> Any:
        return self.meta.get(key, default)

    # ── 상태 ─────────────────────────────────────
    def state(self) -> Dict[str, Any]:
        return read_json(self.dir / "state.json", {}) or {}

    def update_state(self, **patch: Any) -> Dict[str, Any]:
        with _lock:
            st = self.state()
            for k, v in patch.items():
                if v is None:
                    st.pop(k, None)
                elif isinstance(v, dict) and isinstance(st.get(k), dict):
                    st[k] = {**st[k], **v}
                else:
                    st[k] = v
            write_json(self.dir / "state.json", st)
            return st

    def mark(self, stage: str, **info: Any) -> None:
        import time
        self.update_state(stages={stage: {"done": True, "at": time.strftime("%Y-%m-%d %H:%M:%S"), **info}})

    def done(self, stage: str) -> bool:
        return bool(((self.state().get("stages") or {}).get(stage) or {}).get("done"))

    # ── 대본 (편집본 우선) ────────────────────────
    def script(self) -> Optional[Dict[str, Any]]:
        return read_json(self.dir / "script.edit.json") or read_json(self.dir / "script.json")


def create(year: int, subject: str = "컴퓨터일반", exam: str = "국가직 9급", booklet: Optional[str] = None,
           voice: str = "F1", model: str = "opus") -> Job:
    """_assets/index.json 에서 연도·과목의 문제지와 정답표를 찾아 작업을 만든다(있으면 그대로 둔다)."""
    index = read_json(ROOT / "_assets" / "index.json", [])
    entry = next((e for e in index if e["year"] == year and e["subject"] == subject), None)
    if not entry:
        raise ValueError(f"_assets/index.json 에 {year} {subject} 가 없습니다")
    papers = entry["papers"]
    paper = next((p for p in papers if p["booklet"] == booklet), None) if booklet else papers[0]
    if not paper:
        raise ValueError(f"{year} {subject} {booklet}책형 문제지가 없습니다 (있는 책형: {[p['booklet'] for p in papers]})")
    job_id = f"{year}-g9-{SUBJECT_IDS.get(subject, 'subject')}" + (f"-{paper['booklet']}" if len(papers) > 1 else "")
    d = JOBS / job_id
    if not (d / "job.json").exists():
        write_json(d / "job.json", {
            "id": job_id, "year": year, "subject": subject, "booklet": paper["booklet"], "exam": exam,
            "examDate": entry.get("examDate"),
            "title": f"{year} {exam} {subject} 기출 해설",
            "paper": f"_assets/{paper['file']}", "answers": f"_assets/{entry['answers']['file']}",
            "voice": voice, "speed": 1.0, "model": model,
        })
    return Job(job_id)


def all_jobs() -> List[Job]:
    if not JOBS.exists():
        return []
    return [Job(p.name) for p in sorted(JOBS.iterdir()) if (p / "job.json").exists()]
