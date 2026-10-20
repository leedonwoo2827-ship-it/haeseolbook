"""썸네일 1280×720 — 단정 테마: 깊은 남색 + 큰 연도(머스터드) + 덩어리 + 두 줄 문구"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from . import theme as T
from .job import Job
from .log import log


def run(job: Job, force: bool = False) -> Path:
    if job.thumb.exists() and not force:
        log("썸네일: 이미 있음")
        return job.thumb
    m = job.meta
    img = T.paper(T.PALETTE["deep"], seed=42).resize((1280, 720))
    d = ImageDraw.Draw(img)
    T.blob(d, 1010, 380, 250, T.PALETTE["accent"], seed=4)
    T.blob(d, 1210, 70, 90, T.PALETTE["cobalt"], seed=9)
    T.blob(d, -20, 740, 120, T.PALETTE["mustard"], seed=2)
    yr = str(m["year"])
    fy = T.font(T.HEAVY, 210)
    d.text((990 - d.textlength(yr, font=fy) / 2, 270), yr, font=fy, fill=T.PALETTE["mustard"])
    d.text((70, 150), m["subject"], font=T.font(T.HEAVY, 128), fill=(255, 255, 255))
    d.text((74, 310), "기출 20문항 해설", font=T.font(T.BOLD, 72), fill=T.PALETTE["mustard"])
    T.wavy(d, 76, 76 + 330, 410, T.PALETTE["mustard"], amp=6, period=30, width=7)
    tag = f"{m['exam']} · 문항별 챕터"
    f = T.font(T.BOLD, 38)
    d.rounded_rectangle((70, 560, 70 + d.textlength(tag, font=f) + 48, 626), radius=33, fill=(255, 255, 255))
    d.text((94, 569), tag, font=f, fill=T.PALETTE["deep"])
    T.sparkle(d, 760, 120, 30, (255, 255, 255))
    job.out.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(job.thumb, quality=92)
    job.mark("thumb")
    log(f"썸네일 완료: {job.thumb.name}")
    return job.thumb
