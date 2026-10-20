"""영상 테마 「단정 스케치북」 — 팔레트·글꼴·손그림 도형 (PIL 만 사용)

색을 바꾸려면 PALETTE 만 고친다. 문제판·판서·썸네일이 모두 이 값을 읽는다.
"""
from __future__ import annotations

import math
import random
from typing import List, Sequence, Tuple

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from . import FONTS

PALETTE = {
    "ink": (31, 29, 43),          # 제목·먹선
    "paper": (238, 234, 225), "sky": (201, 218, 234), "sage": (214, 224, 206), "apricot": (243, 220, 200),
    "deep": (34, 49, 79),         # 표지·맺음
    "accent": (221, 90, 67),      # 토마토 — 번호·밑줄·✗·정답 원
    "cobalt": (53, 80, 200),      # ✓
    "mustard": (235, 180, 60),    # 형광펜·장식
    "card": (251, 250, 246),
}
BG_CYCLE = ["paper", "sky", "sage", "apricot"]
W, H = 1920, 1080


def font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS / name), size)


BOLD, SEMI, HEAVY = "Pretendard-Bold.otf", "Pretendard-SemiBold.otf", "BlackHanSans-Regular.ttf"


def paper(color: Tuple[int, int, int], seed: int = 7) -> Image.Image:
    """단색 바탕 + 옅은 종이 결(잡티)"""
    rng = np.random.default_rng(seed)
    base = np.empty((H, W, 3), np.float32)
    base[:] = color
    grain = rng.normal(0, 3.0, (H, W, 1)).astype(np.float32)
    fiber = rng.normal(0, 1.2, (1, W, 1)).astype(np.float32)
    return Image.fromarray(np.clip(base + grain + fiber, 0, 255).astype(np.uint8))


def blob(d: ImageDraw.ImageDraw, cx: float, cy: float, r: float, color, seed: int = 1, wobble: float = 0.16) -> None:
    """둥근 덩어리(유기적 모양)"""
    rnd = random.Random(seed)
    ph = [rnd.uniform(0, 2 * math.pi) for _ in range(3)]
    pts = []
    for i in range(72):
        a = 2 * math.pi * i / 72
        k = 1 + wobble * (math.sin(2 * a + ph[0]) * 0.6 + math.sin(3 * a + ph[1]) * 0.3 + math.sin(5 * a + ph[2]) * 0.1)
        pts.append((cx + r * k * math.cos(a), cy + r * k * math.sin(a)))
    d.polygon(pts, fill=color)


def sparkle(d: ImageDraw.ImageDraw, cx: float, cy: float, r: float, color) -> None:
    """네 갈래 반짝이"""
    pts = []
    for i in range(8):
        a = math.pi / 4 * i - math.pi / 2
        rr = r if i % 2 == 0 else r * 0.22
        pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
    d.polygon(pts, fill=color)


def wavy(d: ImageDraw.ImageDraw, x0: float, x1: float, y: float, color, amp: float = 5, period: float = 26, width: int = 5) -> None:
    pts = [(x, y + amp * math.sin((x - x0) / period * 2 * math.pi)) for x in np.arange(x0, x1, 2)]
    d.line(pts, fill=color, width=width, joint="curve")


def card(img: Image.Image, box: Sequence[float], fill=None, shadow=(10, 12)) -> None:
    """먹선 카드 + 비껴 깐 단색 그림자"""
    d = ImageDraw.Draw(img)
    x0, y0, x1, y1 = box
    d.rounded_rectangle((x0 + shadow[0], y0 + shadow[1], x1 + shadow[0], y1 + shadow[1]), radius=18, fill=PALETTE["ink"])
    d.rounded_rectangle(box, radius=18, fill=fill or PALETTE["card"], outline=PALETTE["ink"], width=4)


# ── 손그림 판서 (2배로 그려 줄이면 부드럽다) ─────────────────────────────────
def _jitter(points: List[Tuple[float, float]], amt: float, seed: int) -> List[Tuple[float, float]]:
    rnd = random.Random(seed)
    return [(x + rnd.uniform(-amt, amt), y + rnd.uniform(-amt, amt)) for x, y in points]


def _partial(points: List[Tuple[float, float]], t: float) -> List[Tuple[float, float]]:
    """폴리라인을 길이 비율 t 만큼만 (그려지는 애니메이션)"""
    if t >= 1 or len(points) < 2:
        return points
    seg = [math.dist(a, b) for a, b in zip(points, points[1:])]
    total, acc, out = sum(seg), 0.0, [points[0]]
    goal = total * max(0.0, t)
    for (a, b), s in zip(zip(points, points[1:]), seg):
        if acc + s >= goal:
            k = (goal - acc) / s if s else 0
            out.append((a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k))
            return out
        out.append(b)
        acc += s
    return out


def stroke_paths(kind: str, box: Tuple[float, float, float, float], seed: int) -> List[List[Tuple[float, float]]]:
    """판서 종류별 손그림 경로(이미지 좌표). box = 대상 글자 영역."""
    x0, y0, x1, y1 = box
    h = y1 - y0
    if kind == "circle":
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        rx, ry = (x1 - x0) / 2 + h * 0.55, h * 0.95
        pts = [(cx + rx * math.cos(a), cy + ry * math.sin(a)) for a in np.linspace(-2.2, 2 * math.pi - 1.9, 40)]
        return [_jitter(pts, h * 0.04, seed)]
    if kind == "ul":
        pts = [(x, y1 + h * 0.18 + h * 0.10 * math.sin((x - x0) / max(8, h * 0.9) * 2 * math.pi)) for x in np.linspace(x0, x1, 40)]
        return [_jitter(pts, h * 0.02, seed)]
    if kind == "ok":      # ✓ — 대상 왼쪽에
        cx, cy, s = x0 - h * 0.95, (y0 + y1) / 2, h * 0.65
        return [_jitter([(cx - s * 0.55, cy), (cx - s * 0.1, cy + s * 0.5), (cx + s * 0.7, cy - s * 0.65)], s * 0.04, seed)]
    if kind == "no":      # ✗ — 대상 왼쪽에
        cx, cy, s = x0 - h * 0.95, (y0 + y1) / 2, h * 0.5
        return [_jitter([(cx - s, cy - s), (cx + s, cy + s)], s * 0.05, seed),
                _jitter([(cx + s, cy - s), (cx - s, cy + s)], s * 0.05, seed + 1)]
    return []


def draw_mark(img: Image.Image, kind: str, box: Tuple[float, float, float, float], t: float = 1.0, seed: int = 0) -> None:
    """판서 하나를 진행도 t(0~1)까지 그린다. hl(형광펜)은 반투명 띠."""
    x0, y0, x1, y1 = box
    h = y1 - y0
    if kind == "hl":
        over = Image.new("RGBA", img.size, (0, 0, 0, 0))
        od = ImageDraw.Draw(over)
        xe = x0 + (x1 - x0 + h * 0.3) * min(1.0, t)
        od.rounded_rectangle((x0 - h * 0.15, y0 + h * 0.05, xe, y1 + h * 0.1), radius=int(h * 0.25), fill=PALETTE["mustard"] + (115,))
        img.paste(Image.alpha_composite(img.convert("RGBA"), over).convert("RGB"))
        return
    color = {"circle": PALETTE["accent"], "ul": PALETTE["accent"], "ok": PALETTE["cobalt"], "no": PALETTE["accent"]}.get(kind, PALETTE["accent"])
    width = max(4, int(h * (0.14 if kind in ("ok", "no") else 0.11)))
    paths = stroke_paths(kind, box, seed)
    # 여러 획은 순서대로 그려진다
    n = len(paths)
    d = ImageDraw.Draw(img)
    for i, p in enumerate(paths):
        ti = min(1.0, max(0.0, t * n - i))
        if ti <= 0:
            continue
        pts = _partial(p, ti)
        if len(pts) >= 2:
            d.line(pts, fill=color, width=width, joint="curve")
            r = width / 2
            for (x, y) in (pts[0], pts[-1]):
                d.ellipse((x - r, y - r, x + r, y + r), fill=color)
