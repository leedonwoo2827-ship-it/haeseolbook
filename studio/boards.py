"""문제판 — 원문 문항을 그대로 잘라(다시 그리지 않음) 「단정 스케치북」 화면에 올린다.

  crop(job)            s0 에서: 문항별 고해상도 크롭 boards/crop/qNN.png + 원문 좌표 기하(boards.json)
  frame(job, no, …)    문항 화면(바탕·로고·키커·제목·먹선 카드·원문·쪽수) → (이미지, 원문→화면 변환)
  locate(job, no, t)   판서 대상(보기 번호·ㄱㄴㄷ·글귀)의 원문 위치 → 화면 좌표 / 원문 0–1 좌표
  title_frame(...)     표지·맺음(깊은 남색)

  ┌──────────────────────────────────────────────────────────┐
  │ 07 — 프로세스 메모리                                 07 / 20 │
  │ 프로세스 메모리 배치  ~~~~                                   │
  │ ┌──────────────────────────────────────────────┐ ✦         │
  │ │  원문 문항 (판서가 이 위에 그려진다)               │█         │
  │ └──────────────────────────────────────────────┘█         │
  │                       자막                                │
  └──────────────────────────────────────────────────────────┘
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

import pymupdf as fitz
from PIL import Image, ImageDraw

from . import theme as T
from .job import Job, read_json, write_json
from .log import log

CARD = (96, 238, 1824, 900)       # 원문 카드
PAD = 30
CIRCLED = "①②③④⑤"
CROP_W = 1800


# ── s0: 크롭 ────────────────────────────────────────────────────────────────
def crop(job: Job, force: bool = False) -> Dict[str, Any]:
    out = job.boards / "boards.json"
    if out.exists() and not force:
        return read_json(out)
    regions = read_json(job.book / "regions.json", [])
    quizzes = read_json(job.book / "quizzes.json", [])
    doc = fitz.open(job.paper)
    (job.boards / "crop").mkdir(parents=True, exist_ok=True)
    result: Dict[str, Any] = {"questions": {}}
    for q in quizzes:
        no = q["no"]
        tiles, places, y = [], [], 0
        for r in (r for r in regions if r.get("quizNo") == no):
            page = doc[r["pageNo"] - 1]
            pw, ph = page.rect.width, page.rect.height
            b = r["bbox"]
            rect = fitz.Rect(b["x"] * pw, b["y"] * ph, (b["x"] + b["w"]) * pw, (b["y"] + b["h"]) * ph)
            zoom = CROP_W / rect.width
            pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=rect, alpha=False)
            tiles.append(Image.frombytes("RGB", (pix.width, pix.height), pix.samples))
            places.append({"pageNo": r["pageNo"], "rect": [rect.x0, rect.y0, rect.x1, rect.y1], "zoom": zoom, "oy": y})
            y += pix.height + 24
        img = Image.new("RGB", (max(t.width for t in tiles), max(1, y - 24)), (255, 255, 255))
        yy = 0
        for t in tiles:
            img.paste(t, (0, yy))
            yy += t.height + 24
        name = f"crop/q{no:02d}.png"
        img.save(job.boards / name, optimize=True)
        result["questions"][str(no)] = {"crop": name, "size": list(img.size), "places": places}
    write_json(out, result)
    log(f"s0 문항 크롭 {len(quizzes)}개")
    return result


# ── 화면 ────────────────────────────────────────────────────────────────────
def _chrome(img: Image.Image, job: Job, page_txt: str, dark: bool = False) -> ImageDraw.ImageDraw:
    """쪽수만 (최종 단정 테마는 상단 로고타입·캡션을 뺐다)"""
    d = ImageDraw.Draw(img)
    ink = (255, 255, 255) if dark else T.PALETTE["ink"]
    if page_txt:
        fp = T.font(T.BOLD, 30)
        d.text((W - 72 - d.textlength(page_txt, font=fp), 104), page_txt, font=fp, fill=ink)
    return d


W, H = T.W, T.H


def frame(job: Job, no: int, title: str, total: int = 20) -> Tuple[Image.Image, Dict[str, Any]]:
    """문항 화면과 원문→화면 변환 정보 {s, ox, oy, places}"""
    info = read_json(job.boards / "boards.json")["questions"][str(no)]
    bg = T.BG_CYCLE[(no - 1) % len(T.BG_CYCLE)]
    img = T.paper(T.PALETTE[bg], seed=no)
    d = ImageDraw.Draw(img)
    # 장식: 왼쪽 아래 덩어리 · 카드 오른쪽 위 반짝이
    T.blob(d, -40, H + 10, 190, T.PALETTE["accent"] if no % 2 else T.PALETTE["mustard"], seed=no)
    _chrome(img, job, f"{no:02d} / {total:02d}")
    # 키커 + 제목 + 물결 밑줄
    topic = re.sub(r"^\s*\d+\s*번\s*[·:\-—]\s*", "", title or "").strip() or f"{no}번"
    fk = T.font(T.BOLD, 26)
    d.text((96, 104), f"{no:02d}", font=fk, fill=T.PALETTE["accent"])
    d.text((96 + d.textlength(f"{no:02d}", font=fk) + 14, 104), f"—  {no}번 문항", font=fk, fill=T.PALETTE["ink"])
    ft = T.font(T.BOLD, 54)
    d.text((96, 140), topic, font=ft, fill=T.PALETTE["ink"])
    tw = d.textlength(topic, font=ft)
    T.wavy(d, 98, 98 + min(tw, 220), 214, T.PALETTE["accent"], amp=4, period=22, width=4)
    T.card(img, CARD)
    T.sparkle(d, CARD[2] - 26, CARD[1] - 34, 26, T.PALETTE["ink"])
    T.sparkle(d, CARD[2] + 26, CARD[1] + 4, 13, T.PALETTE["mustard"])
    # 원문
    crop_img = Image.open(job.boards / info["crop"]).convert("RGB")
    bw, bh = CARD[2] - CARD[0] - 2 * PAD, CARD[3] - CARD[1] - 2 * PAD
    s = min(bw / crop_img.width, bh / crop_img.height, 1.0)
    im = crop_img.resize((max(1, int(crop_img.width * s)), max(1, int(crop_img.height * s))), Image.LANCZOS)
    ox = int(CARD[0] + PAD + (bw - im.width) / 2)
    oy = int(CARD[1] + PAD + (bh - im.height) / 2)
    img.paste(im, (ox, oy))
    return img, {"s": s, "ox": ox, "oy": oy, "places": info["places"]}


def _to_screen(geo: Dict[str, Any], place: Dict[str, Any], r: fitz.Rect) -> Tuple[float, float, float, float]:
    rx0, ry0 = place["rect"][0], place["rect"][1]
    z, s = place["zoom"], geo["s"]
    f = lambda x, y: (geo["ox"] + (x - rx0) * z * s, geo["oy"] + (place["oy"] + (y - ry0) * z) * s)
    a, b = f(r.x0, r.y0), f(r.x1, r.y1)
    return (a[0], a[1], b[0], b[1])


def _variants(text: str) -> List[str]:
    t = text.strip().strip("\"'“”‘’")
    out = [t, t.replace(" ", "")]
    if len(t) > 14:
        out += [t[:14], t[:14].replace(" ", "")]
    return [v for i, v in enumerate(out) if v and v not in out[:i]]


def _phrase(page: fitz.Page, clip: fitz.Rect, text: str) -> List[fitz.Rect]:
    """글귀를 「같은 줄의 연속된 단어」로 찾아 그 단어들을 합친 영역 하나로.
    시험지는 양쪽 정렬로 단어 사이가 넓어 search_for 가 글귀 전체를 못 잡는 일이 많다."""
    goal = re.sub(r"\s+", "", text).strip("\"'“”‘’")
    if len(goal) < 2:
        return []
    words = page.get_text("words", clip=clip)      # x0,y0,x1,y1,word,block,line,wno
    for i, w in enumerate(words):
        acc, rect = "", None
        for w2 in words[i:]:
            if (w2[5], w2[6]) != (w[5], w[6]):
                break
            acc += w2[4]
            rect = fitz.Rect(w2[:4]) if rect is None else rect | fitz.Rect(w2[:4])
            if acc.startswith(goal) or goal.startswith(acc) and len(acc) >= len(goal):
                return [rect]
            if not goal.startswith(acc):
                break
    return []


def locate(doc: fitz.Document, geo: Dict[str, Any], target: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """판서 대상 → {screen: (x0,y0,x1,y1), pageNo, norm: (x,y)} . 못 찾으면 None
    target: {"choice": 3} | {"item": "ㄱ"} | {"text": "전역 변수"}"""
    for place in geo["places"]:
        page = doc[place["pageNo"] - 1]
        clip = fitz.Rect(*place["rect"])
        hits: List[fitz.Rect] = []
        if "choice" in target:
            n = int(target["choice"])
            if 1 <= n <= 5:
                hits = page.search_for(CIRCLED[n - 1], clip=clip)
        elif "item" in target:
            sym = str(target["item"]).strip()[:1]
            hits = [h for h in page.search_for(sym, clip=clip)]
            # 항목 기호는 줄 머리(왼쪽)에 있는 것만 — 본문 속 같은 글자 배제
            if hits:
                left = min(h.x0 for h in hits)
                hits = [h for h in hits if h.x0 <= left + 4]
        elif "text" in target:
            hits = _phrase(page, clip, str(target["text"]))
            if not hits:
                for v in _variants(str(target["text"])):
                    hits = page.search_for(v, clip=clip)
                    if hits:
                        break
        if hits:
            r = hits[0]
            if "text" in target and len(hits) > 1:   # 여러 줄에 걸친 글귀 → 첫 줄만
                r = hits[0]
            return {"screen": _to_screen(geo, place, r), "pageNo": place["pageNo"],
                    "norm": (round((r.x0 + r.x1) / 2 / page.rect.width, 4), round((r.y0 + r.y1) / 2 / page.rect.height, 4))}
    return None


def title_frame(job: Job, big: str, second: str, small: str = "") -> Image.Image:
    img = T.paper(T.PALETTE["deep"], seed=99)
    d = ImageDraw.Draw(img)
    T.blob(d, 1500, 560, 330, T.PALETTE["accent"], seed=5)
    T.blob(d, 1730, 120, 120, T.PALETTE["cobalt"], seed=8)
    T.blob(d, -30, -30, 150, T.PALETTE["mustard"], seed=3)
    _chrome(img, job, "", dark=True)
    fb = T.font(T.BOLD, 104)
    d.text((110, 330), big, font=fb, fill=(255, 255, 255))
    d.text((110, 460), second, font=T.font(T.BOLD, 64), fill=T.PALETTE["mustard"])
    T.wavy(d, 114, 114 + 260, 560, T.PALETTE["mustard"], amp=6, period=30, width=6)
    if small:
        d.text((114, 610), small, font=T.font(T.SEMI, 32), fill=(214, 220, 235))
    fy = T.font(T.HEAVY, 260)
    yr = str(job.meta["year"])
    d.text((1500 - d.textlength(yr, font=fy) / 2, 420), yr, font=fy, fill=T.PALETTE["deep"])
    T.sparkle(d, 1260, 250, 40, (255, 255, 255))
    T.sparkle(d, 1810, 820, 26, T.PALETTE["mustard"])
    return img
