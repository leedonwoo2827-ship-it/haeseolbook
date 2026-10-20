"""파이프라인 시험용 샘플 시험지(2단, 자체 작성 문항) + 정답표 + 영상 매핑 예시 생성

  python -I tools/pipeline/make_sample.py content/raw
  → sample-electric.pdf, sample-answers.json, sample-video_map.json

실제 기출이 아닌 자체 작성 문항이다. 영상은 YouTube IFrame API 공식 데모 영상(M7lc1UVf-VE)을 자리표시로 쓴다.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import fitz

FONT = Path("C:/Windows/Fonts/malgun.ttf")
QUESTIONS = [
    ("저항 R=10Ω 에 전류 I=2A 가 흐를 때 소비전력 P[W]는?", ["20", "40", "5", "200"], 2),
    ("직렬로 연결된 4Ω, 6Ω 저항의 합성저항[Ω]은?", ["2.4", "10", "24", "1.5"], 2),
    ("병렬로 연결된 6Ω, 3Ω 저항의 합성저항[Ω]은?", ["9", "4.5", "2", "18"], 3),
    ("정전용량 C=2μF 콘덴서에 100V 를 가했을 때 축적 전하량[C]은?", ["2×10^-4", "2×10^-6", "50", "200"], 1),
    ("60Hz 교류의 주기[ms]에 가장 가까운 값은?", ["6", "16.7", "60", "1.67"], 2),
    ("자기인덕턴스 L=0.5H 에 2A 가 흐를 때 저장 에너지[J]는?", ["0.5", "1", "2", "4"], 2),
    ("실효값 100V 정현파 전압의 최댓값[V]에 가장 가까운 것은?", ["70.7", "100", "141.4", "200"], 3),
    ("역률 0.8, 피상전력 10kVA 일 때 유효전력[kW]은?", ["6", "8", "10", "12.5"], 2),
]


def main() -> None:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "content/raw")
    out.mkdir(parents=True, exist_ok=True)
    doc = fitz.open()
    W, H = 595, 842
    col_w = (W - 3 * 36) / 2
    per_col = 2
    idx = 0
    while idx < len(QUESTIONS):
        page = doc.new_page(width=W, height=H)
        page.insert_font(fontname="kr", fontfile=str(FONT))
        page.insert_text((36, 40), "샘플 전기이론 (파이프라인 시험용 · 자체 작성 문항)", fontname="kr", fontsize=11)
        page.draw_line((W / 2, 56), (W / 2, H - 36), color=(0.6, 0.6, 0.6), width=0.5)
        for col in range(2):
            y = 80
            for _ in range(per_col):
                if idx >= len(QUESTIONS):
                    break
                q, choices, _ans = QUESTIONS[idx]
                x = 36 + col * (col_w + 36)
                rect = fitz.Rect(x, y, x + col_w, y + 60)
                page.insert_textbox(rect, f"{idx + 1}. {q}", fontname="kr", fontsize=10.5, lineheight=1.5)
                cy = y + 70
                for i, c in enumerate(choices):
                    page.insert_text((x + 12, cy + i * 22), f"{'①②③④'[i]} {c}", fontname="kr", fontsize=10.5)
                y += 70 + 4 * 22 + 150  # 풀이 공간
                idx += 1
    pdf = out / "sample-electric.pdf"
    doc.save(pdf)
    (out / "sample-answers.json").write_text(json.dumps({str(i + 1): a for i, (_, _, a) in enumerate(QUESTIONS)}), encoding="utf-8")
    # AI 해설영상이 역으로 넘겨줄 매핑의 예시: 문항당 30초 구간 + 포인터 트랙 일부
    vm = []
    for i in range(len(QUESTIONS)):
        start = 5 + i * 30
        vm.append({"no": i + 1, "youtubeId": "M7lc1UVf-VE", "startSec": start, "endSec": start + 30})
    vm[0]["cues"] = [
        {"t": 8, "pageNo": 1, "x": 0.12, "y": 0.11},
        {"t": 14, "pageNo": 1, "x": 0.40, "y": 0.11},
        {"t": 20, "pageNo": 1, "x": 0.18, "y": 0.22},
        {"t": 30, "pageNo": 1, "x": 0.18, "y": 0.27},
    ]
    (out / "sample-video_map.json").write_text(json.dumps(vm, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"sample → {pdf}")


if __name__ == "__main__":
    main()
