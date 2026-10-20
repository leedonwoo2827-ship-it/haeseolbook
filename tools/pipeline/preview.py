"""검수용: 페이지 이미지 위에 문항 영역(regions.json)과 포인터 트랙(video_map.json cues)을 그려 PNG 로 저장

  python -I tools/pipeline/preview.py content/build/2025-g9-electric
  → content/build/2025-g9-electric/_preview/<n>.png
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("build", type=Path)
    a = ap.parse_args()
    pages = json.loads((a.build / "pages.json").read_text(encoding="utf-8"))
    regions = json.loads((a.build / "regions.json").read_text(encoding="utf-8"))
    vm_file = a.build / "video_map.json"
    video_map = json.loads(vm_file.read_text(encoding="utf-8")) if vm_file.exists() else []
    out = a.build / "_preview"
    out.mkdir(exist_ok=True)
    for p in pages:
        img = Image.open(a.build / p["files"]["sm"]).convert("RGB")
        d = ImageDraw.Draw(img)
        W, H = img.size
        for r in (r for r in regions if r["pageNo"] == p["pageNo"]):
            b = r["bbox"]
            d.rectangle([b["x"] * W, b["y"] * H, (b["x"] + b["w"]) * W, (b["y"] + b["h"]) * H], outline=(37, 99, 235), width=3)
            d.text((b["x"] * W + 4, b["y"] * H + 2), f"Q{r['quizNo']}", fill=(37, 99, 235))
        for v in video_map:
            pts = [(c["x"] * W, c["y"] * H) for c in v.get("cues", []) if c["pageNo"] == p["pageNo"]]
            if len(pts) > 1:
                d.line(pts, fill=(220, 38, 38), width=2)
        img.save(out / f"{p['pageNo']}.png")
    print(f"preview → {out}")


if __name__ == "__main__":
    main()
