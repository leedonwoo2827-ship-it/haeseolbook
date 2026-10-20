"""해설북 스튜디오 — 기출 PDF → 문항별 해설 롱폼 영상 → 유튜브 → 이북(해설북) 연동.

이 저장소 안에서만 돈다. 모델(assets/supertonic)·크롬 프로필(profiles/)·작업물(studio/jobs)은 저장소에 올리지 않는다.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent      # 저장소 루트
STUDIO = ROOT / "studio"
JOBS = STUDIO / "jobs"
FONTS = STUDIO / "fonts"
