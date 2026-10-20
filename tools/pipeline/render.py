"""기출 PDF → 원문 그대로의 페이지 WebP(3단계 해상도) + pages.json + book.json

사용 (큰 문제집은 --pages 로 회차 범위만):
  python -I tools/pipeline/render.py content/raw/2025-electric.pdf content/build/2025-g9-electric \
      --id 2025-g9-electric --title "2025 국가직 9급 전기이론" --exam "국가직 9급" --subject "전기이론" --year 2025 --round "필기"

원문을 다시 그리지 않고 래스터로만 내보낸다(원본 PDF는 배포하지 않음).
"""
from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path

import fitz  # PyMuPDF
from PIL import Image

# 페이지 너비 기준 목표 픽셀: 썸네일 / 폰·기본 / 태블릿 확대·레티나
SIZES = {"xs": 360, "sm": 1200, "hi": 2400}
QUALITY = {"xs": 70, "sm": 82, "hi": 85}


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


def render(pdf: Path, out: Path, page_range: str | None = None) -> list[dict]:
    doc = open_pages(pdf, page_range)
    pages = []
    for i, page in enumerate(doc, start=1):
        rect = page.rect
        for size, target in SIZES.items():
            zoom = target / rect.width
            pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            dest = out / "pages" / size / f"{i}.webp"
            dest.parent.mkdir(parents=True, exist_ok=True)
            img.save(dest, "WEBP", quality=QUALITY[size], method=6)
        pages.append({
            "pageNo": i,
            "width": round(rect.width, 2),
            "height": round(rect.height, 2),
            "files": {s: f"pages/{s}/{i}.webp" for s in SIZES},
        })
        print(f"  page {i}/{doc.page_count}", file=sys.stderr)
    return pages


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdf", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--id", required=True, help="영소문자/숫자/하이픈 (예: 2025-g9-electric)")
    ap.add_argument("--title", required=True)
    ap.add_argument("--exam", required=True)
    ap.add_argument("--subject", required=True)
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--round", default="필기")
    ap.add_argument("--pages", help='PDF 쪽 범위 "a-b" (회차별로 자를 때)')
    a = ap.parse_args()

    a.out.mkdir(parents=True, exist_ok=True)
    pages = render(a.pdf, a.out, a.pages)
    (a.out / "pages.json").write_text(json.dumps(pages, ensure_ascii=False, indent=1), encoding="utf-8")
    book = {"id": a.id, "title": a.title, "exam": a.exam, "subject": a.subject, "year": a.year, "round": a.round}
    (a.out / "book.json").write_text(json.dumps(book, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"rendered {len(pages)} pages → {a.out}")


if __name__ == "__main__":
    main()
