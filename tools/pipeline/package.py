"""교재 빌드 → IP 허브용 아이템 패키지(.hsbpkg.zip)

  python -I tools/pipeline/package.py content/build/2025-g9-electric [--version 1.0.0] [--out dist]

IP 허브는 이 zip 을 아이템으로 보관하고, 출판사 사이트는 선별한 패키지만
관리자 화면(/admin)으로 업로드해 게시한다.

zip 구성
  item.json      {"schema":"ipitem/1","type":"ebook-video","id","version","title",...,"files":{path:sha256}}
  book.json, pages.json, regions.json, quizzes.json, solutions.json, video_map.json
  pages/{xs,sm,hi}/<n>.webp
"""
from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

INCLUDE_JSON = ["book.json", "pages.json", "regions.json", "quizzes.json", "solutions.json", "video_map.json"]
REQUIRED = {"book.json", "pages.json", "quizzes.json"}


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("build", type=Path)
    ap.add_argument("--version", default="1.0.0")
    ap.add_argument("--out", type=Path, default=Path("dist"))
    a = ap.parse_args()

    missing = [f for f in REQUIRED if not (a.build / f).exists()]
    if missing:
        raise SystemExit(f"필수 파일 없음: {missing}")
    book = json.loads((a.build / "book.json").read_text(encoding="utf-8"))
    pages = json.loads((a.build / "pages.json").read_text(encoding="utf-8"))
    quizzes = json.loads((a.build / "quizzes.json").read_text(encoding="utf-8"))
    vm_file = a.build / "video_map.json"
    videos = json.loads(vm_file.read_text(encoding="utf-8")) if vm_file.exists() else []
    sol_file = a.build / "solutions.json"
    if not sol_file.exists():
        print("경고: solutions.json 이 없습니다 (해설 없이 패키징)")

    files: list[Path] = [a.build / f for f in INCLUDE_JSON if (a.build / f).exists()]
    for p in pages:
        files += [a.build / p["files"][s] for s in ("xs", "sm", "hi")]

    item = {
        "schema": "ipitem/1",
        "type": "ebook-video",
        "id": book["id"],
        "version": a.version,
        "title": book["title"],
        "exam": book["exam"],
        "subject": book["subject"],
        "year": book["year"],
        "stats": {"pages": len(pages), "quizzes": len(quizzes), "videos": len(videos),
                  "solutions": len(json.loads(sol_file.read_text(encoding="utf-8"))) if sol_file.exists() else 0},
        "createdAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "files": {f.relative_to(a.build).as_posix(): sha256(f) for f in files},
    }

    a.out.mkdir(parents=True, exist_ok=True)
    dest = a.out / f"{book['id']}-{a.version}.hsbpkg.zip"
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("item.json", json.dumps(item, ensure_ascii=False, indent=1))
        for f in files:
            # WebP 는 이미 압축돼 있으므로 저장만
            z.write(f, f.relative_to(a.build).as_posix(), compress_type=zipfile.ZIP_STORED if f.suffix == ".webp" else zipfile.ZIP_DEFLATED)
    print(f"package → {dest} ({dest.stat().st_size // 1024} KB, {len(files)} files)")


if __name__ == "__main__":
    main()
