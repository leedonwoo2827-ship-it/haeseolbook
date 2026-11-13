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

from . import boards, profile
from . import theme as T
from .job import Job, read_json, write_json
from .log import log

ANIM = (0.34, 0.67, 1.0)
ANIM_STEP = 0.12
PAN = (0.17, 0.33, 0.5, 0.67, 0.83, 1.0)     # 긴 문항 화면 이동(0.5초) — 판서도 같이 그려진다
PAN_STEP = 0.1
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
            tx = profile.texts(m)
            big, second = (tx["title_big"], tx["title_second"]) if sch["kind"] == "intro" \
                else ("수고하셨습니다", "해설북에서 원문 위에 다시 풀어 보세요")
            small = tx["title_small"] if sch["kind"] == "intro" else "문항을 누르면 이 영상의 해설 구간으로 바로 이동합니다"
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
        lo, hi = m.get("range") or (1, 20)
        tv = boards.tall_view(job, no) if job.setting("pan_tall") else None
        if tv:          # 긴 문항: 크게 키운 원문(캔버스)을 판서 따라 위아래로
            base_img, geo = boards.frame_bg(job, no, sch["title"], total=hi, first=lo), tv["geo"]
            base_key = base_key + ["pan3", tv["geo"]["s"]]      # pan3: 카드 안쪽 전체를 흰 바탕 한 장으로
        else:
            base_img, geo = boards.frame(job, no, sch["title"], total=hi, first=lo)
        # 판서 위치 찾기
        placed = []
        for mk in marks:
            loc = boards.locate(doc, geo, mk["target"])
            if loc and mk["line"] < len(q_cues):
                placed.append({**mk, "box": loc["screen"], "pageNo": loc["pageNo"], "norm": loc["norm"],
                               "t": q_cues[mk["line"]]["start"]})
        located[str(no)] = [{k: p[k] for k in ("line", "kind", "target", "pageNo", "norm", "t")} for p in placed]

        idx_of = {id(p): i for i, p in enumerate(placed)}

        def render(done: List[Dict[str, Any]], partial: List[Dict[str, Any]], prog: float, badge: bool, vy: int = 0):
            def draw():
                img = (tv["canvas"] if tv else base_img).copy()
                for p in done:
                    T.draw_mark(img, p["kind"], p["box"], 1.0, seed=no * 100 + idx_of[id(p)])
                for p in partial:
                    T.draw_mark(img, p["kind"], p["box"], prog, seed=no * 100 + idx_of[id(p)])
                if tv:
                    img = boards.tall_compose(base_img, tv, img, vy)
                if badge:
                    _badge(img, answers)
                return img
            return draw

        def aim(boxes: List[Tuple[float, float, float, float]], vy: int) -> int:
            """그 표시들이 화면 안에 들면 그대로, 아니면 보이게 옮긴 vy"""
            if not tv or not boxes:
                return vy
            vh, top_max = tv["view_h"], tv["canvas"].height - tv["view_h"]
            top, bot = min(b[1] for b in boxes), max(b[3] for b in boxes)
            if top >= vy + 24 and bot <= vy + vh - 24:
                return vy
            want = (top + bot) / 2 - vh / 2 if bot - top < vh - 80 else top - 40
            return int(max(0, min(top_max, want)))

        ans_box = []
        if tv:
            loc = boards.locate(doc, geo, {"choice": answers[0]})
            ans_box = [loc["screen"]] if loc else []
        events = sorted({p["t"] for p in placed} | {answer_t})
        vy = 0
        seq.append((sv.save(base_key + ["base"], render([], [], 1.0, False)), c_start))
        for t in events:
            new = [p for p in placed if p["t"] == t]
            done = [p for p in placed if p["t"] < t]
            badge = t >= answer_t
            key_done = [[p["kind"], p["target"]] for p in done]
            to = aim([p["box"] for p in new] or (ans_box if t == answer_t else []), vy)
            steps = PAN if to != vy else ANIM
            if new or to != vy:
                for k, prog in enumerate(steps):
                    e = prog * prog * (3 - 2 * prog)
                    v = int(round(vy + (to - vy) * e))
                    key = base_key + [key_done, [[p["kind"], p["target"]] for p in new], prog, badge] + ([v] if tv else [])
                    seq.append((sv.save(key, render(done, new, prog, badge, v)), t + k * (PAN_STEP if steps is PAN else ANIM_STEP)))
            else:
                seq.append((sv.save(base_key + [key_done, badge] + ([vy] if tv else []), render(done, [], 1.0, badge, vy)), t))
            vy = to
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
