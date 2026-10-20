"""s0 원문 준비: 기출 PDF → 이북 빌드(페이지 WebP·문항 영역·문항 텍스트) + 공식 정답 → quizzes.json

기존 파이프라인(tools/pipeline/render.py, regions.py)을 같은 파이썬으로 부른다.
"""
from __future__ import annotations

import subprocess
import sys

from . import ROOT, answers, boards
from .job import Job, read_json, write_json
from .log import log

PIPE = ROOT / "tools" / "pipeline"


def _py(script: str, *args: str) -> None:
    proc = subprocess.run([sys.executable, "-I", "-W", "ignore", str(PIPE / script), *args],
                          capture_output=True, encoding="utf-8", errors="replace",
                          env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"})
    if proc.returncode != 0:
        raise RuntimeError(f"{script} 실패: {(proc.stderr or proc.stdout)[-600:]}")
    for line in (proc.stdout or "").strip().splitlines()[-3:]:
        log(f"  {line}")


def run(job: Job, force: bool = False) -> None:
    m = job.meta
    book = job.book
    if force or not (book / "pages.json").exists():
        log(f"s0 원문 페이지 렌더: {job.paper.name}")
        _py("render.py", str(job.paper), str(book), "--id", job.id, "--title", m["title"], "--exam", m["exam"],
            "--subject", m["subject"], "--year", str(m["year"]), "--round", f"{m['booklet']}책형")
    if force or not (book / "regions.json").exists():
        log("s0 문항 영역 찾기")
        _py("regions.py", str(job.paper), str(book))
    key = answers.for_booklet(job.answers_pdf, m["subject"], m["booklet"])
    questions = read_json(book / "questions.json", [])
    if len(questions) != 20:
        raise RuntimeError(f"문항 {len(questions)}개만 찾았습니다(20개여야 함) — book/_preview 로 확인하세요")
    write_json(book / "quizzes.json", [
        {"no": q["no"], "answer": key[q["no"] - 1][0], "answers": key[q["no"] - 1], "choiceCount": 4, "keywords": []}
        for q in questions
    ])
    multi = [q["no"] for q in questions if len(key[q["no"] - 1]) > 1]
    log(f"s0 정답 20개 반영" + (f" (복수 정답 문항: {multi})" if multi else ""))
    boards.crop(job, force)
    job.mark("s0", quizzes=20)
