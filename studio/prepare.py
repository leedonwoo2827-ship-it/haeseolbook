"""s0 원문 준비: 기출 PDF → 이북 빌드(페이지 WebP·문항 영역·문항 텍스트) + 공식 정답 → quizzes.json

기존 파이프라인(tools/pipeline/render.py, regions.py)을 같은 파이썬으로 부른다.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

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


def _run_mock(job: Job, force: bool) -> None:
    """모의고사: 07/<mNN>/exam.pdf(1단 46배판) 에서 이 과목 문항이 있는 쪽만 이북으로, 정답·대본은 xam-local2 것을 그대로."""
    import shutil
    m = job.meta
    lo, hi = m["range"]
    book = job.book
    if force or not (book / "pages.json").exists() or not (book / "regions.json").exists():
        # 회차 시험지(40문항) 에서 이 과목 쪽만 잘라 작업 폴더의 paper.pdf 로 — 이후 크롭·판서 위치·이북 쪽 번호가 모두 이 PDF 기준
        full_pdf = Path(m.get("paperFull") or m["paper"])
        log(f"s0 원문: {full_pdf.parent.name}/{full_pdf.name} 의 {lo}~{hi}번 쪽 찾기")
        full = job.dir / "_full"
        _py("regions.py", str(full_pdf), str(full), "--columns", "1")
        pages = sorted({r["pageNo"] for r in read_json(full / "regions.json", []) if lo <= r["quizNo"] <= hi})
        if not pages:
            raise RuntimeError(f"{lo}~{hi}번 문항을 시험지에서 찾지 못했습니다")
        import pymupdf as fitz
        doc = fitz.open(full_pdf)
        doc.select(list(range(pages[0] - 1, pages[-1])))
        part_pdf = job.dir / "paper.pdf"
        doc.save(part_pdf)
        doc.close()
        if m.get("paper") != str(part_pdf):
            m.update(paperFull=str(full_pdf), paper=str(part_pdf), pages=[pages[0], pages[-1]])
            write_json(job.dir / "job.json", m)
        _py("render.py", str(part_pdf), str(book), "--id", job.book_id, "--title", m["title"], "--exam", m["exam"],
            "--subject", m["subject"], "--year", str(m["year"]), "--round", m["round_label"])
        _py("regions.py", str(part_pdf), str(book), "--columns", "1", "--first", str(lo))
        # 과목 경계가 한 쪽에 같이 있으면 다른 과목 문항이 딸려 온다 — 이 과목 것만 남긴다
        write_json(book / "regions.json", [r for r in read_json(book / "regions.json", []) if lo <= r["quizNo"] <= hi])
        write_json(book / "questions.json", [q for q in read_json(book / "questions.json", []) if lo <= q["no"] <= hi])
    key = {int(k): int(v) for k, v in read_json(job.answers_pdf, {}).items()}
    questions = read_json(book / "questions.json", [])
    if len(questions) != hi - lo + 1:
        raise RuntimeError(f"문항 {len(questions)}개만 찾았습니다({hi - lo + 1}개여야 함) — book/_preview 로 확인하세요")
    regions = read_json(book / "regions.json", [])
    write_json(book / "quizzes.json", [{
        "no": q["no"], "answer": key[q["no"]], "answers": [key[q["no"]]],
        "choiceCount": max(4, sum(1 for r in regions if r.get("kind") == "choice" and r["quizNo"] == q["no"])),
        "keywords": [],
    } for q in questions])
    n_choice = sum(1 for r in regions if r.get("kind") == "choice")
    log(f"s0 정답 {len(questions)}개 반영 · 보기 칸 {n_choice}개(원문을 눌러 채점)")
    # 대본: xam-local2 가 쓴 문항별 대본을 그대로 가져온다 → s1 은 Claude 없이 조립만
    src = Path(m["scriptSrc"])
    job.scripts.mkdir(parents=True, exist_ok=True)
    copied = 0
    for q in questions:
        a, b = src / f"q{q['no']:02d}.json", job.scripts / f"q{q['no']:02d}.json"
        if a.exists() and (force or not b.exists()):
            shutil.copyfile(a, b)
            copied += 1
    log(f"s0 대본 {copied}개 가져옴 ({src})")
    boards.crop(job, force)
    job.mark("s0", quizzes=len(questions))


def run(job: Job, force: bool = False) -> None:
    m = job.meta
    if m.get("kind") == "mock":
        return _run_mock(job, force)
    book = job.book
    if force or not (book / "pages.json").exists():
        log(f"s0 원문 페이지 렌더: {job.paper.name}")
        _py("render.py", str(job.paper), str(book), "--id", job.book_id, "--title", m["title"], "--exam", m["exam"],
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
