"""교재 한글(HWPX) 만들기 — xam-local3 의 변환기를 그 프로젝트 venv 로 부른다

  문제편   07/<mNN>/exam.hwpx            (교재 회차마다, exam.html 이 있어야 함 = xam-local3 「시험지 굽기」 뒤)
  정답·해설 07/_textbook/answers_mAA-mBB.hwpx  (+ .pdf · 영상을 올린 과목은 QR)
  교재 한 권 07/_textbook/textbook_mAA-mBB.hwpx (문제편 전부 + 정답·해설편)

★ xam-local3 는 「작업 폴더 화면에서 고른 책」(data/books.json active)으로 돈다. 그대로 부르면 그 화면에서
  마지막에 고른 책(예: 컴활 실기)에 만들어지므로, 이 시리즈의 책 폴더로 고정하고(paths.using_book)
  제목도 그 책의 시험지 제목으로 고정한다.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from .log import log

XAM_DEFAULT = Path(r"D:\00work\261109-xam-local3")

# xam-local3 안에서 돌릴 코드 — argv: 회차들, 책 폴더, 제목, 문제편 있으면 건너뛰기(1/0). 결과는 마지막 줄 JSON
_CODE = r"""
import json, os, sys
from services.book import paths
from services.export import answerbook as a, ebookexam as ex
rcs, book, label, skip = sys.argv[1].split(","), sys.argv[2], sys.argv[3], sys.argv[4] == "1"
if label:
    ex._label = lambda: label
out = {"exam": {}}
with paths.using_book(book):
    for rc in rcs:
        f = os.path.join(ex.round_dir(rc), "exam.html")
        if skip and os.path.isfile(os.path.join(ex.round_dir(rc), "exam.hwpx")):
            out["exam"][rc] = {"skipped": True}
        else:
            out["exam"][rc] = a.to_hwpx(f) if os.path.isfile(f) else {"error": "exam.html 없음 — xam-local3 에서 시험지를 먼저 구우세요"}
        print("PROGRESS", rc, "skip" if out["exam"][rc].get("skipped") else "", flush=True)
    r = a.build(rcs, pdf=True)
out["answers"] = {k: r.get(k) for k in ("hwpx", "hwpx_error", "book_hwpx", "book_error", "qr_missing", "pdf_error")}
print("RESULT " + json.dumps(out, ensure_ascii=False), flush=True)
"""

_TITLE = re.compile(r"<title>(.*?)\s*모의고사\s*\d+회\s*</title>", re.S)


def book_label(series: Dict[str, Any], rcs: Iterable[str]) -> str:
    """이 책의 시험지 제목에서 「… 모의고사 NN회」 앞부분 — 예: 「컴퓨터활용능력 2급 필기 (2027)」"""
    for rc in rcs:
        f = Path(series["book"]) / "07" / rc / "exam.html"
        if f.is_file():
            m = _TITLE.search(f.read_text(encoding="utf-8", errors="replace")[:4000])
            if m:
                return m.group(1).strip()
    return str(series.get("exam") or "")


def run(series: Dict[str, Any], rounds: Optional[Iterable[int]] = None, skip_existing_exam: bool = False) -> Dict[str, Any]:
    xam = Path(series.get("xam") or XAM_DEFAULT)
    py = xam / "venv" / "Scripts" / "python.exe"
    if not py.exists():
        raise RuntimeError(f"xam-local3 가 없습니다: {py} — _assets/mocks.json 의 \"xam\" 에 경로를 적으세요")
    rcs = [f"m{n:02d}" for n in sorted(series.get("textbook") or [] if rounds is None else rounds)]
    if not rcs:
        raise RuntimeError("교재 회차가 없습니다 (_assets/mocks.json 의 textbook)")
    label = book_label(series, rcs)
    log(f"── 교재 한글 만들기: {rcs[0]}~{rcs[-1]} · {label} (xam-local3 변환기)")
    env = {"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    import os
    p = subprocess.Popen([str(py), "-c", _CODE, ",".join(rcs), str(series["book"]), label, "1" if skip_existing_exam else "0"],
                         cwd=xam, env=dict(os.environ, **env),
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding="utf-8", errors="replace")
    result: Dict[str, Any] = {}
    tail = []
    for line in p.stdout:  # type: ignore[union-attr]
        line = line.rstrip()
        if line.startswith("PROGRESS "):
            w = line.split()
            log(f"  ✓ {w[1]} 문제편 한글" + (" (있어서 그대로)" if w[2:] == ["skip"] else ""))
        elif line.startswith("RESULT "):
            result = json.loads(line[7:])
        elif line:
            tail.append(line)
    if p.wait() != 0 or not result:
        raise RuntimeError("변환 실패: " + "\n".join(tail[-8:]))
    for rc, r in result["exam"].items():
        if r.get("error"):
            log(f"  △ {rc} 문제편: {r['error']}")
    ans = result["answers"]
    for k, what in (("hwpx", "정답·해설편"), ("book_hwpx", "교재 한 권(문제+해설)")):
        if ans.get(k):
            log(f"  ✓ {what}: {ans[k]}")
    for k in ("hwpx_error", "book_error", "pdf_error"):
        if ans.get(k):
            log(f"  △ {ans[k]}")
    if ans.get("qr_missing"):
        log(f"  · QR 아직(영상 안 올림): {', '.join(ans['qr_missing'])} — 올린 뒤 다시 누르면 찍힙니다")
    log(f"교재 한글 끝 → {Path(series['book']) / '07' / '_textbook'}")
    return result
