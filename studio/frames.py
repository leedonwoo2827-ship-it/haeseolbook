"""s4 화면: 문장 시각(timing.cues)에 맞춰 판서가 쌓이는 정지 화면들을 만든다 → frames.json

문항 장: 바탕 화면 → 판서가 달린 문장이 시작될 때 그 표시가 0.36초 동안 그려지고(3컷) 그대로 남는다.
        정답 장면부터 「정답 ③」 배지. 표지·맺음은 한 장.
같은 내용의 화면은 해시 이름으로 저장해 다시 그리지 않는다(boards/frames/<hash>.jpg).
판서 좌표(원문 0–1)는 이북 포인터로도 쓰도록 marks.located.json 에 남긴다.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Tuple

import pymupdf as fitz
from PIL import Image, ImageDraw

from . import boards
from . import theme as T
from .job import Job, read_json, write_json
from .log import log

ANIM = (0.34, 0.67, 1.0)
ANIM_STEP = 0.12
CIRCLED = "①②③④⑤"


def _badge(img: Image.Image, answers: List[int]) -> None:
    d = ImageDraw.Draw(img)
    text = "정답 " + ", ".join(CIRCLED[a - 1] for a in answers)
    f = T.font(T.BOLD, 40)
    w = d.textlength(text, font=f)
    x1, y0 = boards.CARD[2] - 30, boards.CARD[1] + 24
    d.rounded_rectangle((x1 - w - 56, y0, x1, y0 + 64), radius=32, fill=T.PALETTE["accent"])
    d.text((x1 - w - 28, y0 + 8), text, font=f, fill=(255, 255, 255))


class Saver:
    def __init__(self, job: Job):
        self.dir = job.boards / "frames"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.used: set = set()

    def save(self, key: Any, draw) -> str:
        name = hashlib.sha1(json.dumps(key, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()[:16] + ".jpg"
        p = self.dir / name
        if not p.exists():
            draw().save(p, quality=90)
        self.used.add(name)
        return f"frames/{name}"


def run(job: Job, force: bool = False) -> List[Dict[str, Any]]:
    timing = read_json(job.audio / "timing.json")
    script = job.script()
    if not timing or not script:
        raise RuntimeError("timing.json / 대본이 없습니다 — 목소리(s3)를 먼저")
    doc = fitz.open(job.paper)
    sv = Saver(job)
    seq: List[Tuple[str, float]] = []     # (이미지, 시작 시각)
    located: Dict[str, Any] = {}
    chapters = timing["chapters"]
    cues = timing["cues"]
    scenes = {s["n"]: s for s in timing["scenes"]}
    m = job.meta
    for ci, ch in enumerate(chapters):
        c_start = ch["start"]
        sch = script["chapters"][ci]
        if sch.get("kind") in ("intro", "outro"):
            big, second = (f"{m['year']} {m['subject']}", f"{m['exam']} 기출 20문항 해설") if sch["kind"] == "intro" \
                else ("수고하셨습니다", "해설북에서 원문 위에 다시 풀어 보세요")
            small = "원문: 인사혁신처 공개 기출 · 최종정답 기준" if sch["kind"] == "intro" else "문항을 누르면 이 영상의 해설 구간으로 바로 이동합니다"
            seq.append((sv.save(["title", m, big, second, small], lambda: boards.title_frame(job, big, second, small)), c_start))
            continue
        no = sch["quiz"]
        sq = read_json(job.scripts / f"q{no:02d}.json")
        answers = sq["answers"]
        marks = (read_json(job.scripts / f"q{no:02d}.marks.json") or {}).get("marks", [])
        q_cues = [c for c in cues if c["chapter"] == ch["i"]]
        answer_scene = max(c["scene"] for c in q_cues)
        answer_t = scenes[answer_scene]["start"]
        base_key = ["q", job.id, no, sch["title"]]
        base_img, geo = boards.frame(job, no, sch["title"])
        # 판서 위치 찾기
        placed = []
        for mk in marks:
            loc = boards.locate(doc, geo, mk["target"])
            if loc and mk["line"] < len(q_cues):
                placed.append({**mk, "box": loc["screen"], "pageNo": loc["pageNo"], "norm": loc["norm"],
                               "t": q_cues[mk["line"]]["start"]})
        located[str(no)] = [{k: p[k] for k in ("line", "kind", "target", "pageNo", "norm", "t")} for p in placed]

        idx_of = {id(p): i for i, p in enumerate(placed)}

        def render(done: List[Dict[str, Any]], partial: List[Dict[str, Any]], prog: float, badge: bool):
            def draw():
                img = base_img.copy()
                for p in done:
                    T.draw_mark(img, p["kind"], p["box"], 1.0, seed=no * 100 + idx_of[id(p)])
                for p in partial:
                    T.draw_mark(img, p["kind"], p["box"], prog, seed=no * 100 + idx_of[id(p)])
                if badge:
                    _badge(img, answers)
                return img
            return draw

        events = sorted({p["t"] for p in placed} | {answer_t})
        seq.append((sv.save(base_key + ["base"], render([], [], 1.0, False)), c_start))
        for t in events:
            new = [p for p in placed if p["t"] == t]
            done = [p for p in placed if p["t"] < t]
            badge = t >= answer_t
            key_done = [[p["kind"], p["target"]] for p in done]
            if new:
                for k, prog in enumerate(ANIM):
                    key = base_key + [key_done, [[p["kind"], p["target"]] for p in new], prog, badge]
                    seq.append((sv.save(key, render(done, new, prog, badge)), t + k * ANIM_STEP))
            else:
                seq.append((sv.save(base_key + [key_done, badge], render(done, [], 1.0, badge)), t))
    # 시작 시각 → 길이
    seq.sort(key=lambda x: x[1])
    frames = []
    for (img, t), nxt in zip(seq, seq[1:] + [(None, timing["duration"])]):
        dur = round(nxt[1] - t, 3)
        if dur > 0.01:
            frames.append({"img": img, "start": round(t, 3), "dur": dur})
    write_json(job.boards / "frames.json", frames)
    write_json(job.boards / "marks.located.json", located)
    for p in (job.boards / "frames").glob("*.jpg"):     # 안 쓰는 옛 화면 정리
        if p.name not in sv.used:
            p.unlink()
    total_marks = sum(len(v) for v in located.values())
    job.mark("s4", frames=len(frames), marks=total_marks)
    log(f"s4 화면 {len(frames)}컷 (판서 {total_marks}개, 이미지 {len(sv.used)}장)")
    return frames
