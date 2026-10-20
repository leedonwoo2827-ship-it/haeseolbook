"""인사혁신처 「최종정답」 PDF → 과목·책형별 정답 20개.

표는 텍스트로 「번호 | 과목명 | 책형 | 정답×20 | (다른 책형 | 정답×20) | 다음 번호 …」 순으로 나온다.
복수 정답은 한 칸에 "1, 2" 처럼, 전항 정답은 "전항 정답"/"모두 정답" 으로 나온다(→ [1,2,3,4]).

  python -m studio answers _assets/2025/2025_국가9급_공채_최종정답.pdf --subject 컴퓨터일반 --booklet 나
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List

import pymupdf as fitz

BOOKLETS = set("가나다라마바")
_ANS = re.compile(r"^[1-5](\s*,\s*[1-5])*$")
_ALL = re.compile(r"(전항|모두)\s*정답")


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s)


def _tokens(pdf: Path) -> List[str]:
    doc = fitz.open(pdf)
    out: List[str] = []
    for page in doc:
        out += [t.strip() for t in page.get_text().split("\n") if t.strip()]
    return out


def parse(pdf: Path, subject: str) -> Dict[str, List[List[int]]]:
    """{책형: [[정답들] × 20]} — 문항마다 정답 목록(보통 1개)."""
    toks = _tokens(pdf)
    want = _norm(subject)
    for i, t in enumerate(toks):
        if _norm(t) != want:
            continue
        result: Dict[str, List[List[int]]] = {}
        j = i + 1
        while j < len(toks) and toks[j] in BOOKLETS:
            booklet, j = toks[j], j + 1
            answers: List[List[int]] = []
            while len(answers) < 20 and j < len(toks):
                tok = toks[j]
                if _ALL.search(tok):
                    answers.append([1, 2, 3, 4])
                elif _ANS.match(tok):
                    answers.append(sorted({int(x) for x in re.findall(r"[1-5]", tok)}))
                else:
                    break
                j += 1
            if len(answers) != 20:
                raise ValueError(f"{pdf.name}: {subject} {booklet}책형 정답이 {len(answers)}개만 읽혔습니다")
            result[booklet] = answers
        if result:
            return result
    raise ValueError(f"{pdf.name}: '{subject}' 과목 행을 찾지 못했습니다")


def for_booklet(pdf: Path, subject: str, booklet: str) -> List[List[int]]:
    rows = parse(pdf, subject)
    if booklet not in rows:
        raise ValueError(f"{pdf.name}: {subject} 에 {booklet}책형이 없습니다 (있는 책형: {', '.join(rows)})")
    return rows[booklet]
