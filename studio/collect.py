"""모으기 — 각 부의 작업이 끝난 뒤 사이트에 올릴 책(PDF)을 한 폴더로 모은다

  1부 끝  핵심요약본   jobs/<lecture_job>/out/<summary_src>/*.pdf  → 과목 순서대로 PDF 1편 (+ 과목별 hwpx 복사)
  2부 끝  최종모의고사 <book>/07/mNN/exam.pdf ×(1~5회)           → 문제편 PDF 1편
                       <book>/07/_textbook/answers_mAA-mBB.pdf   → 해설편 PDF 1편 (없거나 낡았으면 xam-local3 로 먼저 굽기)
                       (+ 회차 문제편·해설편·교재 한 권 hwpx 복사)

모이는 곳: deliver/<시리즈 코드>/1부-핵심요약본 · 2부-최종모의고사/  (+ _모음.json = 원본 경로·시각·쪽수)
hwpx 는 사람이 따로 다듬는 원본이라 합치지 않고 복사만 한다. 복사본(하드링크 아님) — 고쳐도 원본은 그대로.
"""
from __future__ import annotations

import json
import re
import shutil
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import ROOT
from .log import log

DELIVER = ROOT / "deliver"
PARTS = {1: "1부-핵심요약본", 2: "2부-최종모의고사"}
MANIFEST = "_모음.json"
_TITLE = re.compile(r"<title>(.*?)</title>", re.S)


# ── 원본 찾기 ────────────────────────────────────────────────────────────────
def out_dir(series: Dict[str, Any], part: int) -> Path:
    return DELIVER / series["code"] / PARTS[part]


def final_rounds(series: Dict[str, Any]) -> List[str]:
    return [f"m{n:02d}" for n in sorted(series.get("final_rounds") or [1, 2, 3, 4, 5])]


def _span(rcs: List[str]) -> str:
    return f"{int(rcs[0][1:])}~{int(rcs[-1][1:])}회" if len(rcs) > 1 else f"{int(rcs[0][1:])}회"


def summary_dir(series: Dict[str, Any]) -> Optional[Path]:
    """1부 이론편(문제 뺀 판) PDF 폴더 — mocks.json 의 summary_src (lecture_job 의 out 기준)"""
    job = series.get("lecture_job")
    if not job:
        return None
    return ROOT / "jobs" / job / "out" / (series.get("summary_src") or "textbook_theory")


def _subject_title(pdf: Path) -> str:
    """같은 이름의 .html 제목(같은 폴더 → 바로 위 폴더, 예: textbook/2차 의 PDF ↔ textbook/ 의 HTML) → 없으면 파일 이름"""
    for h in (pdf.with_suffix(".html"), pdf.parent.parent / (pdf.stem + ".html")):
        if not h.is_file():
            continue
        m = _TITLE.search(h.read_text(encoding="utf-8", errors="replace")[:4000])
        if m and m.group(1).strip():
            return m.group(1).strip()
    return pdf.stem


def _sources(series: Dict[str, Any], part: int) -> List[Dict[str, Any]]:
    """[{role, label, path}] — role: pdf(합칠 것) · ans(해설편 PDF) · copy(복사만)"""
    rows: List[Dict[str, Any]] = []
    if part == 1:
        d = summary_dir(series)
        pdfs = sorted(d.glob("*.pdf")) if d and d.is_dir() else []
        for p in pdfs:
            rows.append({"role": "pdf", "label": f"이론 PDF · {_subject_title(p)}", "path": p})
            rows.append({"role": "copy", "label": f"이론 한글 · {p.stem}", "path": p.with_suffix(".hwpx")})
        if not pdfs:
            rows.append({"role": "pdf", "label": "이론 PDF (1부 교재 굽기 뒤 생김)", "path": (d or Path("?")) / "*.pdf"})
        return rows
    seven = Path(series["book"]) / "07"
    rcs = final_rounds(series)
    for rc in rcs:
        rows.append({"role": "pdf", "label": f"{int(rc[1:])}회 문제 PDF", "path": seven / rc / "exam.pdf"})
    tag = f"{rcs[0]}-{rcs[-1]}" if len(rcs) > 1 else rcs[0]
    rows.append({"role": "ans", "label": f"{_span(rcs)} 정답·해설 PDF", "path": seven / "_textbook" / f"answers_{tag}.pdf"})
    rows.append({"role": "copy", "label": f"{_span(rcs)} 정답·해설 한글", "path": seven / "_textbook" / f"answers_{tag}.hwpx"})
    rows.append({"role": "copy", "label": f"{_span(rcs)} 교재 한 권 한글(문제+해설)", "path": seven / "_textbook" / f"textbook_{tag}.hwpx"})
    for rc in rcs:
        rows.append({"role": "copy", "label": f"{int(rc[1:])}회 문제 한글", "path": seven / rc / "exam.hwpx", "as": f"{rc}_exam.hwpx"})
    return rows


def _outputs(series: Dict[str, Any], part: int) -> List[Tuple[str, str]]:
    """[(파일 이름, 설명)] — 합친 PDF 들"""
    short = series.get("short") or series["code"]
    if part == 1:
        return [(f"{short}_핵심요약본.pdf", "핵심요약본 PDF (과목 전부 1편)")]
    span = _span(final_rounds(series))
    return [(f"{short}_최종모의고사_{span}_문제편.pdf", f"최종모의고사 {span} 문제편 PDF"),
            (f"{short}_최종모의고사_{span}_해설편.pdf", f"최종모의고사 {span} 해설편 PDF")]


# ── 상태 ─────────────────────────────────────────────────────────────────────
def _stamp(p: Path) -> Optional[float]:
    try:
        return p.stat().st_mtime
    except OSError:
        return None


def _when(t: Optional[float]) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(t)) if t else ""


def _answers_stale(series: Dict[str, Any]) -> Optional[str]:
    """해설편 PDF 를 (다시) 구워야 하나 — 없거나, 회차 시험지(exam.html)가 그보다 새로우면 그 이유"""
    ans = next(r["path"] for r in _sources(series, 2) if r["role"] == "ans")
    t = _stamp(ans)
    if t is None:
        return "해설편 PDF 가 아직 없습니다"
    seven = Path(series["book"]) / "07"
    newer = [rc for rc in final_rounds(series) if (_stamp(seven / rc / "exam.html") or 0) > t]
    return f"{', '.join(newer)} 시험지가 해설편보다 새롭습니다" if newer else None


def status(series: Dict[str, Any], part: int) -> Dict[str, Any]:
    od = out_dir(series, part)
    man = {}
    try:
        man = json.loads((od / MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    seen = man.get("sources") or {}
    srcs, changed = [], []
    for r in _sources(series, part):
        t = _stamp(r["path"])
        if t and str(r["path"]) in seen and t > seen[str(r["path"])] + 1:
            changed.append(r["label"])
        srcs.append({"label": r["label"], "path": str(r["path"]), "role": r["role"], "ok": t is not None, "time": _when(t)})
    outs = []
    for name, what in _outputs(series, part):
        f = od / name
        outs.append({"name": name, "label": what, "ok": f.is_file(), "time": _when(_stamp(f)),
                     "pages": (man.get("pages") or {}).get(name), "mb": round(f.stat().st_size / 1e6, 1) if f.is_file() else None})
    copies = [{"name": r.get("as") or Path(r["path"]).name, "label": r["label"],
               "ok": (od / (r.get("as") or Path(r["path"]).name)).is_file()}
              for r in _sources(series, part) if r["role"] == "copy"]
    need = [s["label"] for s in srcs if not s["ok"] and s["role"] == "pdf"]
    note = None
    if part == 2:
        note = _answers_stale(series)
    return {"part": part, "title": PARTS[part].split("-", 1)[1], "dir": str(od), "built": man.get("built", ""),
            "sources": srcs, "outputs": outs, "copies": copies, "missing": need, "changed": changed,
            "answers_note": note, "rounds": _span(final_rounds(series)) if part == 2 else ""}


# ── 모으기 ───────────────────────────────────────────────────────────────────
def _merge(pdfs: List[Tuple[Path, str]], dst: Path) -> int:
    """PDF 여러 개를 차례로 이어 한 편으로 — 원본마다 책갈피 한 줄"""
    import pymupdf
    out = pymupdf.open()
    toc = []
    for p, title in pdfs:
        with pymupdf.open(p) as src:
            toc.append([1, title, out.page_count + 1])
            out.insert_pdf(src)
    out.set_toc(toc)
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(".tmp.pdf")
    out.save(tmp, garbage=3, deflate=True)
    n = out.page_count
    out.close()
    tmp.replace(dst)
    return n


def _pages(p: Path) -> int:
    import pymupdf
    with pymupdf.open(p) as d:
        return d.page_count


def run(series: Dict[str, Any], part: int) -> Dict[str, Any]:
    if part not in PARTS:
        raise ValueError("part 는 1(핵심요약본) 또는 2(최종모의고사)")
    title = PARTS[part].split("-", 1)[1]
    log(f"── 모으기: {series.get('short') or series['code']} {part}부 {title}")
    if part == 2:
        why = _answers_stale(series)
        if why:
            log(f"  · {why} — xam-local3 로 해설편부터 굽습니다")
            from . import hwpx
            hwpx.run(series, rounds=series.get("final_rounds") or [1, 2, 3, 4, 5], skip_existing_exam=True)
    srcs = _sources(series, part)
    missing = [r for r in srcs if r["role"] in ("pdf", "ans") and not Path(r["path"]).is_file()]
    if missing:
        raise RuntimeError("원본이 없습니다: " + ", ".join(f"{r['label']} ({r['path']})" for r in missing))
    od = out_dir(series, part)
    od.mkdir(parents=True, exist_ok=True)
    outs = _outputs(series, part)
    pages: Dict[str, int] = {}
    if part == 1:
        pdfs = [(r["path"], r["label"].split(" · ", 1)[-1]) for r in srcs if r["role"] == "pdf"]
        pages[outs[0][0]] = _merge(pdfs, od / outs[0][0])
    else:
        pdfs = [(r["path"], r["label"].replace(" PDF", "")) for r in srcs if r["role"] == "pdf"]
        pages[outs[0][0]] = _merge(pdfs, od / outs[0][0])
        ans = next(r["path"] for r in srcs if r["role"] == "ans")
        shutil.copy2(ans, od / outs[1][0])
        pages[outs[1][0]] = _pages(od / outs[1][0])
    for name, what in outs:
        log(f"  ✓ {what}: {name} ({pages[name]}쪽)")
    copied = 0
    for r in srcs:
        if r["role"] == "copy":
            p = Path(r["path"])
            if p.is_file():
                shutil.copy2(p, od / (r.get("as") or p.name))
                copied += 1
            else:
                log(f"  △ 없음(건너뜀): {r['label']} — {p}")
    if copied:
        log(f"  ✓ 한글 원본 {copied}개 복사")
    man = {"code": series["code"], "part": part, "built": time.strftime("%Y-%m-%d %H:%M:%S"), "pages": pages,
           "sources": {str(r["path"]): _stamp(Path(r["path"])) for r in srcs if Path(r["path"]).is_file()}}
    (od / MANIFEST).write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"모으기 끝 → {od}")
    return man
