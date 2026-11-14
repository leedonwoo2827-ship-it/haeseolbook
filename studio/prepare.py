"""s0 원문 준비: 기출 PDF → 이북 빌드(페이지 WebP·문항 영역·문항 텍스트) + 공식 정답 → quizzes.json

기존 파이프라인(tools/pipeline/render.py, regions.py)을 같은 파이썬으로 부른다.
"""
from __future__ import annotations

import re
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


_BOLD_FONTS = [Path(r"C:\Windows\Fonts\malgunbd.ttf"), ROOT / "studio" / "fonts" / "malgunbd.ttf"]


def _renumber(page, old: int, new: int) -> bool:
    """쪽에서 문항 번호 글자(「24.」, 굵은 글꼴, 왼쪽 여백)를 지우고 같은 자리·크기·색으로 「1.」을 쓴다."""
    import pymupdf as fitz
    hit = None
    for b in page.get_text("dict")["blocks"]:
        for ln in b.get("lines", []):
            for s in ln["spans"]:
                if s["text"].strip() == f"{old}." and "bold" in s["font"].lower():
                    if hit is None or s["bbox"][0] < hit["bbox"][0]:
                        hit = s
    if not hit:
        return False
    x0, y0, x1, y1 = hit["bbox"]
    page.add_redact_annot(fitz.Rect(x0, y0 + 1, x1, y1 - 1), fill=False)
    page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE, graphics=fitz.PDF_REDACT_LINE_ART_NONE)
    font = next((f for f in _BOLD_FONTS if f.exists()), None)
    c = hit["color"]
    page.insert_text(hit["origin"], f"{new}.", fontsize=hit["size"], fontname="qnum" if font else "hebo",
                     fontfile=str(font) if font else None,
                     color=((c >> 16 & 255) / 255, (c >> 8 & 255) / 255, (c & 255) / 255))
    return True


def _run_lecture(job: Job, force: bool) -> None:
    """3부 강 행: 여러 회차(11~20회)에서 이 강에 배정된 문항만 — 문항이 있는 쪽을 원래 시험지에서 이어 붙여 paper.pdf,
    문항은 강 안에서 1번부터 새로 센다. 문항 영역(regions)은 쪽 비율 좌표라 쪽 번호만 바꿔 옮긴다.
    화면에는 문항 영역만 잘려 나가므로(boards.crop) 같은 쪽의 다른 문항은 보이지 않는다."""
    import shutil
    import pymupdf as fitz
    m = job.meta
    book, src_book = job.book, Path(m["book_dir"]) / "07"
    qs = m["questions"]
    full = {}
    for rc in sorted({f"m{q['round']:02d}" for q in qs}):       # 회차마다 문항 영역 한 번(작업 폴더에 남겨 다시 안 함)
        d = job.dir / "_full" / rc
        if force or not (d / "regions.json").exists():
            log(f"s0 원문: {rc}/exam.pdf 문항 영역 찾기")
            _py("regions.py", str(src_book / rc / "exam.pdf"), str(d), "--columns", "1")
        full[rc] = {"regions": read_json(d / "regions.json", []), "questions": read_json(d / "questions.json", []),
                    "key": {int(k): int(v) for k, v in (read_json(src_book / rc / "answers.json", {}) or {}).items()}}

    if force or not (book / "pages.json").exists() or not (book / "regions.json").exists():
        order, page_of = [], {}                  # (회차, 원래 쪽) → 새 쪽
        for q in qs:
            rc = f"m{q['round']:02d}"
            pgs = sorted({r["pageNo"] for r in full[rc]["regions"] if int(r["quizNo"]) == q["no"]})
            if not pgs:
                raise RuntimeError(f"{q['round']}회 {q['no']}번을 시험지에서 찾지 못했습니다")
            for p in pgs:
                if (rc, p) not in page_of:
                    order.append((rc, p))
                    page_of[(rc, p)] = len(order)
        out = fitz.open()
        for rc, p in order:
            with fitz.open(src_book / rc / "exam.pdf") as src:
                out.insert_pdf(src, from_page=p - 1, to_page=p - 1)
        # 시험지 위 원래 번호(「24.」)를 강 안 번호(「1.」)로 — 화면에 원래 회차·번호가 드러나지 않게
        for i, q in enumerate(qs, 1):
            rc = f"m{q['round']:02d}"
            first = min(r["pageNo"] for r in full[rc]["regions"] if int(r["quizNo"]) == q["no"])
            if not _renumber(out[page_of[(rc, first)] - 1], q["no"], i):
                log(f"  · {q['round']}회 {q['no']}번: 시험지에서 번호 글자를 못 찾아 그대로 둠")
        part_pdf = job.dir / "paper.pdf"
        out.save(part_pdf)
        out.close()
        if m.get("paper") != str(part_pdf):
            m["paper"] = str(part_pdf)
            write_json(job.dir / "job.json", m)
        _py("render.py", str(part_pdf), str(book), "--id", job.book_id, "--title", m["title"], "--exam", m["exam"],
            "--subject", m["subject"], "--year", str(m["year"]), "--round", m["round_label"])
        regions, questions = [], []
        for i, q in enumerate(qs, 1):
            rc = f"m{q['round']:02d}"
            for r in full[rc]["regions"]:
                if int(r["quizNo"]) == q["no"]:
                    regions.append({**r, "quizNo": i, "pageNo": page_of[(rc, r["pageNo"])]})
            src_q = next((x for x in full[rc]["questions"] if int(x["no"]) == q["no"]), None)
            first_page = min(page_of[(rc, r["pageNo"])] for r in full[rc]["regions"] if int(r["quizNo"]) == q["no"])
            questions.append({**(src_q or {}), "no": i, "pageNo": first_page, "round": q["round"], "origNo": q["no"]})
        write_json(book / "regions.json", regions)
        write_json(book / "questions.json", questions)
        log(f"s0 원문: {len(qs)}문항 · {len(order)}쪽을 {len({r for r, _ in order})}개 회차에서 이어 붙임")

    questions = read_json(book / "questions.json", [])
    regions = read_json(book / "regions.json", [])
    if len(questions) != len(qs):
        raise RuntimeError(f"문항 {len(questions)}개만 있습니다({len(qs)}개여야 함) — s0 --force 로 다시")
    write_json(book / "quizzes.json", [{
        "no": i, "answer": full[f"m{q['round']:02d}"]["key"][q["no"]], "answers": [full[f"m{q['round']:02d}"]["key"][q["no"]]],
        "choiceCount": max(4, sum(1 for r in regions if r.get("kind") == "choice" and r["quizNo"] == i)),
        "keywords": [],
    } for i, q in enumerate(qs, 1)])
    # 대본: 원래 회차의 문항별 대본 — 번호는 강 안 번호로, 장 제목은 「1번 · 주제」(원래 회차·번호는 source 에만)
    job.scripts.mkdir(parents=True, exist_ok=True)
    copied = 0
    for i, q in enumerate(qs, 1):
        a, b = src_book / f"m{q['round']:02d}" / "script" / f"q{q['no']:02d}.json", job.scripts / f"q{i:02d}.json"
        if not a.exists():
            raise RuntimeError(f"{a} 가 없습니다 — xam-local 로 {q['round']}회 대본을 먼저 구우세요")
        if force or not b.exists():
            d = read_json(a)
            topic = re.sub(r"^\s*\d+\s*번\s*[·:\-]?\s*", "", d.get("chapter_title") or "")
            d.update(no=i, chapter_title=f"{i}번" + (f" · {topic}" if topic else ""),
                     source={"round": q["round"], "no": q["no"]})
            write_json(b, d)
            copied += 1
    log(f"s0 대본 {copied}개 가져옴 (강 안 번호로)")
    boards.crop(job, force)
    job.mark("s0", quizzes=len(qs))


def run(job: Job, force: bool = False) -> None:
    m = job.meta
    if m.get("unit") == "lecture":
        return _run_lecture(job, force)
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
