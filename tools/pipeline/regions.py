"""기출 PDF에서 문항별 영역(bbox)과 문항 텍스트를 추출한다.

페이지마다 1단/2단을 자동 판별한다(국가직 시험지는 보통 2단, 일반 문제집은 1단, 섞여 있어도 된다).
각 단에서 줄 머리의 "1." / "1)" / "문 1." 같은 문항 번호 앵커를 찾고,
다음 앵커(또는 단 끝)까지를 그 문항 영역으로 본다.
문항이 단·페이지를 넘어가면 이어지는 조각을 같은 번호의 영역으로 추가한다.

사용:
  python -I tools/pipeline/regions.py content/raw/2025-electric.pdf content/build/2025-g9-electric \
      [--answers 정답.json] [--columns auto|1|2] [--pages a-b] [--first N]

산출물(사람이 검수 후 확정):
  regions.json   [{pageNo, kind:"quiz", quizNo, bbox:{x,y,w,h}}]   (0–1 정규화)
  questions.json [{no, pageNo, text}]   (해설 생성 explain.py 입력)
  quizzes.json   [{no, answer, choiceCount}]   (--answers 지정 시. 정답표 {"1":3,"2":1,...})

검수는 preview.py 로 영역을 그려 확인한다.
"""
from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import fitz

# 문항 번호 앵커: "1.", "12)", "문 3.", "1000." (번호가 이어지는 문제집 대비 4자리까지)
ANCHOR = re.compile(r"^\s*(?:문\s*)?(\d{1,4})\s*[.)](?:\s|$)")  # "문  6." 처럼 번호만 있는 줄도 (2022)
CHOICE = re.compile(r"[①②③④⑤]")
MARGIN = 0.006  # bbox 여유 (페이지 비율)
HEADER, FOOTER = 0.035, 0.985  # 머리말("○○ 가책형 1쪽") 띠만 제외. 국가직 B4 시험지는 본문이 위아래 3% 까지 찬다


def open_pages(pdf: Path, pages: str | None) -> fitz.Document:
    """PDF 를 열고 --pages "a-b" 범위만 남긴다(교재의 1쪽 = PDF 의 a쪽). 1000제 같은 큰 PDF 를 회차별로 자를 때 쓴다."""
    doc = fitz.open(pdf)
    if pages:
        a, _, b = pages.partition("-")
        start, end = int(a), int(b or a)
        if not (1 <= start <= end <= doc.page_count):
            raise SystemExit(f"--pages {pages} 가 PDF 쪽수(1-{doc.page_count}) 범위를 벗어납니다")
        doc.select(list(range(start - 1, end)))
    return doc


@dataclass
class Line:
    page: int
    col: int
    x0: float
    y0: float
    x1: float
    y1: float
    text: str
    # 이 줄이 속한 단의 가로 범위 (문항 영역 폭으로 쓴다)
    cx0: float = 0.0
    cx1: float = 0.0


@dataclass
class Quiz:
    no: int
    parts: list[list[Line]] = field(default_factory=list)


def detect_columns(raw: list[tuple[float, float, float, float, str]], w: float) -> int:
    """페이지가 1단인지 2단인지 판별.
    가운데를 가로지르는 긴 줄이 거의 없고, 오른쪽 절반에서 시작하는 줄이 충분하면 2단."""
    if not raw:
        return 1
    mid = w / 2
    spanning = sum(1 for x0, _, x1, _, _ in raw if x0 < mid - 0.03 * w and x1 > mid + 0.03 * w)
    right = sum(1 for x0, *_ in raw if x0 >= mid - 0.01 * w)
    return 2 if right >= 3 and spanning <= max(1, len(raw) // 10) else 1


def page_lines(page: fitz.Page, pno: int, columns: int | None) -> tuple[list[Line], int]:
    """페이지의 본문 줄(머리말·쪽번호 제외)과 단 수. columns=None 이면 페이지마다 자동 판별"""
    w, h = page.rect.width, page.rect.height
    raw = []
    for b in page.get_text("dict")["blocks"]:
        for l in b.get("lines", []):
            text = "".join(s["text"] for s in l["spans"]).strip()
            if not text:
                continue
            x0, y0, x1, y1 = l["bbox"]
            if y1 < h * HEADER or y0 > h * FOOTER:
                continue
            raw.append((x0, y0, x1, y1, text))
    cols = columns or detect_columns(raw, w)
    out = [Line(pno, min(cols - 1, int(x0 / (w / cols))) if cols > 1 else 0, x0, y0, x1, y1, text) for x0, y0, x1, y1, text in raw]
    # 단마다 실제 글자가 있는 가로 범위. 2단이면 짧은 문항도 탭하기 쉽게 단 경계까지 넓힌다
    left_margin = min((l.x0 for l in out), default=0.0)
    for c in range(cols):
        mine = [l for l in out if l.col == c]
        if not mine:
            continue
        lo, hi = min(l.x0 for l in mine), max(l.x1 for l in mine)
        if cols == 2:
            hi = max(hi, w / 2 - 0.02 * w if c == 0 else w - left_margin)
        for l in mine:
            l.cx0, l.cx1 = lo, hi
    # 단 순서 → 위에서 아래
    out.sort(key=lambda l: (l.col, round(l.y0, 1), l.x0))
    return out, cols


def find_quizzes(doc: fitz.Document, columns: int | None, first: int = 1) -> tuple[list[Quiz], dict[int, int]]:
    quizzes: list[Quiz] = []
    layout: dict[int, int] = {}
    expected = first
    current: Quiz | None = None
    for pno, page in enumerate(doc, start=1):
        lines, cols = page_lines(page, pno, columns)
        layout[pno] = cols
        for col in range(cols):
            col_lines = [l for l in lines if l.col == col]
            if current is not None and col_lines:
                current.parts.append([])  # 단/페이지가 바뀌면 새 조각
            pending: Line | None = None  # 「문」 혼자 있는 줄 (2018~2022 시험지: "문" ↵ "1. …")
            for line in col_lines:
                if line.text.strip() == "문":
                    pending = line
                    continue
                m = ANCHOR.match(line.text)
                # 번호가 순서대로 증가할 때만 앵커로 인정 (보기 안의 "1." 같은 오탐 방지)
                if m and int(m.group(1)) == expected:
                    current = Quiz(expected, [[]])
                    quizzes.append(current)
                    expected += 1
                if pending is not None:
                    if current is not None:
                        current.parts[-1].append(pending)  # 새 문항이면 그 문항 머리에, 아니면 이어지는 줄로
                    pending = None
                if current is not None:
                    current.parts[-1].append(line)
    for q in quizzes:
        q.parts = [p for p in q.parts if p]
    return quizzes, layout


def to_regions(doc: fitz.Document, quizzes: list[Quiz]) -> list[dict]:
    regions = []
    for q in quizzes:
        for part in q.parts:
            page = doc[part[0].page - 1]
            pw, ph = page.rect.width, page.rect.height
            # 가로는 그 단의 글자 범위 전체, 세로는 문항 줄 범위
            x0 = max(0.0, part[0].cx0 / pw - MARGIN * 2)
            x1 = min(1.0, part[0].cx1 / pw + MARGIN * 2)
            y0 = max(0.0, min(l.y0 for l in part) / ph - MARGIN)
            y1 = min(1.0, max(l.y1 for l in part) / ph + MARGIN)
            regions.append({
                "pageNo": part[0].page, "kind": "quiz", "quizNo": q.no,
                "bbox": {"x": round(x0, 4), "y": round(y0, 4), "w": round(x1 - x0, 4), "h": round(y1 - y0, 4)},
            })
    return regions


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdf", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--columns", default="auto", choices=["auto", "1", "2"], help="단 수. auto(기본)는 페이지마다 1단/2단 자동 판별")
    ap.add_argument("--pages", help='PDF 쪽 범위 "a-b" (render.py 와 같게)')
    ap.add_argument("--first", type=int, default=1, help="이 회차의 첫 문항 번호 (번호가 이어지는 문제집이면 51, 101 …)")
    ap.add_argument("--answers", type=Path, help='정답표 JSON {"1":3,"2":1,...}')
    a = ap.parse_args()

    doc = open_pages(a.pdf, a.pages)
    quizzes, layout = find_quizzes(doc, None if a.columns == "auto" else int(a.columns), a.first)
    if not quizzes:
        raise SystemExit("문항 번호를 찾지 못했습니다. 스캔 PDF라면 OCR 후 다시 실행하세요 (--columns 도 확인).")
    regions = to_regions(doc, quizzes)
    questions = [{
        "no": q.no, "pageNo": q.parts[0][0].page,
        "text": "\n".join(l.text for part in q.parts for l in part),
    } for q in quizzes]

    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "regions.json").write_text(json.dumps(regions, ensure_ascii=False, indent=1), encoding="utf-8")
    (a.out / "questions.json").write_text(json.dumps(questions, ensure_ascii=False, indent=1), encoding="utf-8")

    if a.answers:
        key = {int(k): int(v) for k, v in json.loads(a.answers.read_text(encoding="utf-8")).items()}
        missing = [q.no for q in quizzes if q.no not in key]
        if missing:
            raise SystemExit(f"정답표에 없는 문항: {missing}")
        qz = [{
            "no": q.no, "answer": key[q.no],
            "choiceCount": max(4, len(set(CHOICE.findall(questions[i]["text"])))),
        } for i, q in enumerate(quizzes)]
        (a.out / "quizzes.json").write_text(json.dumps(qz, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"{len(quizzes)} quizzes, {len(regions)} regions → {a.out}")
    print("pages: " + " ".join(f"{p}쪽={c}단" for p, c in layout.items()))
    found = [q.no for q in quizzes]
    gaps = [n for n in range(found[0], found[-1] + 1) if n not in found]
    if gaps:
        print(f"경고: 찾지 못한 문항 번호 {gaps} — preview 로 확인하세요")


if __name__ == "__main__":
    main()
