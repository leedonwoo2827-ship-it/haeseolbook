"""교재 한글(HWPX) 만들기 — xam-local2 의 변환기를 그 프로젝트 venv 로 부른다

  문제편   07/<mNN>/exam.hwpx            (교재 회차마다, exam.html 이 있어야 함 = xam-local2 「시험지 굽기」 뒤)
  정답·해설 07/_textbook/answers_mAA-mBB.hwpx  (+ .pdf · 영상을 올린 과목은 QR)
  교재 한 권 07/_textbook/textbook_mAA-mBB.hwpx (문제편 전부 + 정답·해설편)
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Dict

from .log import log

XAM_DEFAULT = Path(r"D:\00work\261024-xam-local2")

# xam-local2 안에서 돌릴 코드 — 결과는 마지막 줄 JSON
_CODE = r"""
import json, os, sys
from services.export import answerbook as a, ebookexam as ex
rcs = sys.argv[1].split(",")
out = {"exam": {}}
for rc in rcs:
    f = os.path.join(ex.round_dir(rc), "exam.html")
    out["exam"][rc] = a.to_hwpx(f) if os.path.isfile(f) else {"error": "exam.html 없음 — xam-local2 에서 시험지를 먼저 구우세요"}
    print("PROGRESS", rc, flush=True)
r = a.build(rcs, pdf=True)
out["answers"] = {k: r.get(k) for k in ("hwpx", "hwpx_error", "book_hwpx", "book_error", "qr_missing", "pdf_error")}
print("RESULT " + json.dumps(out, ensure_ascii=False), flush=True)
"""


def run(series: Dict[str, Any]) -> Dict[str, Any]:
    xam = Path(series.get("xam") or XAM_DEFAULT)
    py = xam / "venv" / "Scripts" / "python.exe"
    if not py.exists():
        raise RuntimeError(f"xam-local2 가 없습니다: {py} — _assets/mocks.json 의 \"xam\" 에 경로를 적으세요")
    rcs = [f"m{n:02d}" for n in sorted(series.get("textbook") or [])]
    if not rcs:
        raise RuntimeError("교재 회차가 없습니다 (_assets/mocks.json 의 textbook)")
    log(f"── 교재 한글 만들기: {rcs[0]}~{rcs[-1]} (xam-local2 변환기)")
    env = {"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    import os
    p = subprocess.Popen([str(py), "-c", _CODE, ",".join(rcs)], cwd=xam, env=dict(os.environ, **env),
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding="utf-8", errors="replace")
    result: Dict[str, Any] = {}
    tail = []
    for line in p.stdout:  # type: ignore[union-attr]
        line = line.rstrip()
        if line.startswith("PROGRESS "):
            log(f"  ✓ {line.split()[1]} 문제편 한글")
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
