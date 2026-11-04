"""작업(job) = 시험지 한 회차 = 영상 한 편 = 이북 교재 한 권.

종류(job.json "kind"):
  g9    국가직 9급 기출 — id `2025-g9-computer`, _assets/index.json 의 원문·인사혁신처 정답 PDF
  mock  자사 모의고사 — id `<code>-<mNN>-p<과목>` (예: com2-m06-p1), _assets/mocks.json 의 시리즈.
        xam-local2 가 굽는 `<book>/07/<mNN>/` (1단 46배판 exam.pdf · answers.json · script/qNN.json) 을 쓴다.
        한 회차 40문항을 과목(20문항)마다 영상 한 편·이북 한 권으로 나눈다 — 유튜브 한 편 20~25분.

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

SUBJECT_IDS = {"컴퓨터일반": "computer", "컴퓨터 일반": "computer", "스프레드시트 일반": "spreadsheet", "정보보호론": "infosec", "국어": "korean", "영어": "english", "한국사": "history"}


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

    @property
    def book_id(self) -> str:
        """이북 교재 id — 서버 규칙(영소문자·숫자·하이픈)에 맞게 책형 한글을 a·b·c·d 로"""
        return self.id.translate(str.maketrans({"가": "a", "나": "b", "다": "c", "라": "d"}))

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


# ── 자사 모의고사 ─────────────────────────────────────────────────────────────
MOCKS = ROOT / "_assets" / "mocks.json"


def mock_series() -> List[Dict[str, Any]]:
    """[{code, name, short, exam, year, book, rounds:[1..10], textbook:[1..5], public:[]}]

    textbook  교재(인쇄·한글)에 실리는 회차 — 나머지는 이북(e-test) 회차. 어디에 실리는지만 정한다.
    public    유튜브 공개 회차 — 나머지는 일부공개(링크로만). 교재/이북과 따로 정한다.
    """
    return read_json(MOCKS, []) or []


def save_mock_series(entry: Dict[str, Any]) -> None:
    rows = [e for e in mock_series() if e["code"] != entry["code"]] + [entry]
    write_json(MOCKS, rows)


def mock_label(series: Dict[str, Any], n: int) -> str:
    """판(교재/이북)마다 1회부터 다시 센다 — 교재 m01~m05 → 01~05회, 이북(e-test) m06~m10 → 01~05회"""
    textbook = sorted(series.get("textbook") or [])
    group = textbook if n in textbook else sorted(r for r in series.get("rounds") or [] if r not in textbook)
    return f"{group.index(n) + 1 if n in group else n:02d}회"


def mock_parts(book: Path, rc: str) -> List[Dict[str, Any]]:
    """회차의 과목 구간 — 07/<rc>/script/qNN.json 의 subject 가 바뀌는 곳에서 나눈다.
    [{part: 1, subject: "컴퓨터 일반", range: [1, 20]}, {part: 2, …, range: [21, 40]}]"""
    d = Path(book) / "07" / rc / "script"
    items = sorted(d.glob("q??.json"))
    if not items:
        raise FileNotFoundError(f"{d} 에 대본이 없습니다 — xam-local2 「이북 시험지」로 {rc} 를 먼저 구우세요")
    parts: List[Dict[str, Any]] = []
    for f in items:
        q = read_json(f)
        if not parts or parts[-1]["subject"] != q.get("subject"):
            parts.append({"part": len(parts) + 1, "subject": q.get("subject") or "", "range": [q["no"], q["no"]]})
        parts[-1]["range"][1] = q["no"]
    return parts


def create_mock(code: str, rc: str, part: int, voice: str = "F1", model: str = "opus") -> Job:
    series = next((e for e in mock_series() if e["code"] == code), None)
    if not series:
        raise ValueError(f"_assets/mocks.json 에 {code} 시리즈가 없습니다 (python -m studio new-mock …)")
    book = Path(series["book"])
    pinfo = next((p for p in mock_parts(book, rc) if p["part"] == part), None)
    if not pinfo:
        raise ValueError(f"{rc} 에 {part}과목이 없습니다")
    job_id = f"{code}-{rc}-p{part}"
    d = JOBS / job_id
    n = int(rc[1:])
    rl = mock_label(series, n)
    if (d / "job.json").exists():          # 회차 이름을 바꿨으면 기존 작업에도 반영
        meta = read_json(d / "job.json")
        if meta.get("round_label") != rl:
            meta["round_label"] = rl
            meta["title"] = f"{series.get('short') or series['exam']} 필기 모의고사 {rl} {pinfo['subject']} 해설"
            write_json(d / "job.json", meta)
    else:
        src = book / "07" / rc
        write_json(d / "job.json", {
            "id": job_id, "kind": "mock", "code": code, "series": series["name"],
            "exam": series["exam"], "short": series.get("short") or series["exam"], "year": int(series.get("year") or 0),
            "subject": pinfo["subject"], "round": rc, "round_label": rl, "part": part, "range": pinfo["range"],
            "booklet": "", "title": f"{series.get('short') or series['exam']} 필기 모의고사 {rl} {pinfo['subject']} 해설",
            "paper": str(src / "exam.pdf"), "answers": str(src / "answers.json"), "scriptSrc": str(src / "script"),
            "dest": "textbook" if n in (series.get("textbook") or []) else "ebook",
            "visibility": "public" if n in (series.get("public") or []) else "unlisted",
            "voice": voice, "speed": 1.0, "model": model,
        })
    return Job(job_id)


def record_mock_video(job: Job, url: str) -> Optional[Path]:
    """모의고사 영상 주소 → <교재>/07/_textbook/videos.json {"m01-p1": url} — xam-local2 정답·해설편이 QR 로 찍는다"""
    if job.setting("kind") != "mock" or not url:
        return None
    src = Path(job.meta.get("paperFull") or job.meta["paper"])      # <교재>/07/<mNN>/exam.pdf
    p = src.parent.parent / "_textbook" / "videos.json"
    with _lock:
        cur = read_json(p, {}) or {}
        cur[f"{job.meta['round']}-p{job.meta['part']}"] = url
        write_json(p, cur)
    return p


MOCK_ID = __import__("re").compile(r"^(?P<code>[a-z0-9]+)-(?P<rc>m\d{2})-p(?P<part>\d)$")


def resolve(item: str, subject: str = "컴퓨터일반") -> Job:
    """대시보드·대기열의 항목 → 작업. `2025|나` 는 9급 기출, `com2-m06-p1` 은 모의고사(없으면 만든다)"""
    if (JOBS / item / "job.json").exists():
        return Job(item)
    m = MOCK_ID.match(item)
    if m:
        return create_mock(m["code"], m["rc"], int(m["part"]))
    year, _, booklet = item.partition("|")
    return create(int(year), subject, booklet=booklet or None)


def all_jobs() -> List[Job]:
    if not JOBS.exists():
        return []
    return [Job(p.name) for p in sorted(JOBS.iterdir()) if (p / "job.json").exists()]
