"""잡 데이터 → 섹션별 scene.json (화이트보드 페이지가 읽는 장면 기술서).

    jobs/J/out/Lxx/parts/<sid>.timing.json   슬라이드 순서·오디오 길이·자막 파일
    jobs/J/manuscripts/Lxx/<sid>.json         제목·불릿·그림·기출 카드

★ 시간축은 기존 영상과 같게 둔다: 슬라이드 길이 = audio_sec + 0.45 (오디오 없으면 4초, s4_stitch 와 같은 규칙),
  섹션 길이 = 기존 parts/<sid>.mp4 의 실제 길이(마지막 슬라이드가 차이를 흡수). 그래서 자막·챕터를 그대로 쓴다.
★ 언제 쓰는가(at)는 여기서 정한다: 불릿은 그 말이 처음 나오는 자막 큐 시작에 맞춘다(글자 2-gram 겹침).
  어디에 쓰는가(배치)는 페이지(main.js)가 글자 폭을 재서 정한다.
"""
from __future__ import annotations

import html
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Dict, List, Optional

from longform.s4_stitch import TAIL_SEC, _read_srt
from longform.util import ffprobe_duration, read_json

CIRCLED = "①②③④⑤⑥⑦⑧⑨"
_PUNCT = re.compile(r"[\s·,.:;!?()\[\]{}'\"“”‘’「」『』<>~\-—–/·…]+")


def _grams(s: str) -> set:
    s = _PUNCT.sub("", s)
    return {s[i:i + 2] for i in range(len(s) - 1)} or ({s} if s else set())


def _score(needle: str, hay: str) -> float:
    a = _grams(needle)
    return len(a & _grams(hay)) / len(a) if a else 0.0


def match_times(texts: List[str], cues: List[Dict[str, Any]], t_min: float, t_max: float,
                floor: float = 0.0) -> List[float]:
    """texts 를 말하는 시각(슬라이드 기준 초). 순서를 지키며 큐를 앞에서부터 찾고, 못 찾으면 사이를 고르게."""
    out: List[Optional[float]] = []
    ci = 0
    for tx in texts:
        best, bj = 0.0, None
        for j in range(ci, len(cues)):
            sc = _score(tx, cues[j]["text"])
            if sc >= .34:
                best, bj = sc, j
                break
            if sc > best:
                best, bj = sc, j
        if bj is not None and best >= .18:
            out.append(max(t_min, cues[bj]["a"]))
            ci = bj + 1 if best >= .34 else bj
        else:
            out.append(None)
    # 못 찾은 것은 앞뒤 사이에 고르게, 그리고 단조 증가(최소 간격 floor)
    n = len(out)
    for i in range(n):
        if out[i] is None:
            j = i
            while j < n and out[j] is None:
                j += 1
            a = out[i - 1] if i > 0 else t_min
            b = out[j] if j < n else t_max
            for k in range(i, j):
                out[k] = a + (b - a) * (k - i + 1) / (j - i + 1)
    res: List[float] = []
    for v in out:
        v = max(float(v), t_min)
        if res:
            v = max(v, res[-1] + floor)
        res.append(min(v, t_max))
    return res


class _Card(HTMLParser):
    """기출 카드 html → {head, q, passage:[{type:'p'|'table'|'svg'|'pre', src}], choices:[]}"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.d: Dict[str, Any] = {"head": "", "q": "", "passage": [], "choices": []}
        self.stack: List[str] = []
        self.cls: List[str] = []
        self.buf: Optional[List[str]] = None
        self.raw: Optional[List[str]] = None   # table/svg 원문 수집
        self.raw_tag = ""
        self.raw_depth = 0
        self.mode = ""

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if self.raw is not None:
            if tag == self.raw_tag:
                self.raw_depth += 1
            self.raw.append(self.get_starttag_text() or f"<{tag}>")
            return
        c = a.get("class", "")
        if tag == "div" and c in ("qh", "qq", "qp"):
            self.mode = c
            if c != "qp":
                self.buf = []
        elif tag in ("table", "svg") and self.mode == "qp":
            self.raw, self.raw_tag, self.raw_depth = [self.get_starttag_text() or f"<{tag}>"], tag, 1
        elif tag in ("p", "pre") and self.mode == "qp":
            self.buf = []
            self.mode_p = tag
        elif tag == "li":
            self.buf = []
        elif tag == "br" and self.buf is not None:
            self.buf.append("\n")

    def handle_startendtag(self, tag, attrs):
        if self.raw is not None:
            self.raw.append(self.get_starttag_text() or f"<{tag}/>")
        elif tag == "br" and self.buf is not None:
            self.buf.append("\n")

    def handle_endtag(self, tag):
        if self.raw is not None:
            self.raw.append(f"</{tag}>")
            if tag == self.raw_tag:
                self.raw_depth -= 1
                if self.raw_depth == 0:
                    self.d["passage"].append({"type": self.raw_tag, "src": "".join(self.raw)})
                    self.raw = None
            return
        if tag == "div" and self.mode in ("qh", "qq") and self.buf is not None:
            self.d["head" if self.mode == "qh" else "q"] = "".join(self.buf).strip()
            self.buf, self.mode = None, ""
        elif tag in ("p", "pre") and self.buf is not None and self.mode == "qp":
            t = "".join(self.buf)
            t = t.strip("\n") if tag == "pre" else re.sub(r"\s+", " ", t).strip()
            if t:
                self.d["passage"].append({"type": tag, "src": t})
            self.buf = None
        elif tag == "li" and self.buf is not None:
            self.d["choices"].append(re.sub(r"\s+", " ", "".join(self.buf)).strip())
            self.buf = None
        elif tag == "div" and self.mode == "qp":
            self.mode = ""

    def handle_data(self, data):
        if self.raw is not None:
            self.raw.append(html.escape(data, quote=False))
        elif self.buf is not None:
            self.buf.append(data)


def parse_card(src: str) -> Dict[str, Any]:
    p = _Card()
    p.feed(src)
    return p.d


def _kind(ts: Dict[str, Any], ms: Optional[Dict[str, Any]]) -> str:
    if not ts.get("data_id"):
        return "cover" if int(ts.get("no") or 0) == 1 else "closing"
    if ms and ms.get("card"):
        return "quiz"
    if (ms or {}).get("title", ts.get("title", "")).startswith("정답"):
        return "answer"
    return "normal"


def build_section(job_dir: Path, lid: str, sid: str, *, first: bool, last: bool) -> Dict[str, Any]:
    tm = read_json(job_dir / "out" / lid / "parts" / f"{sid}.timing.json")
    man = read_json(job_dir / "manuscripts" / lid / f"{sid}.json")
    part = job_dir / "out" / lid / "parts" / f"{sid}.mp4"
    by_id: Dict[str, Dict[str, Any]] = {}
    groups_seen: List[str] = []
    for g in man.get("groups") or []:
        for s in g.get("slides") or []:
            by_id[s["id"]] = {**s, "_group": g.get("title", "")}
    figs = man.get("figs") or []

    slides: List[Dict[str, Any]] = []
    subs: List[Dict[str, Any]] = []
    t = 0.0
    for ts in tm.get("slides") or []:
        au = float(ts.get("audio_sec") or 0)
        dur = (au + TAIL_SEC) if au > 0 else 4.0
        ms = by_id.get(ts.get("data_id") or "")
        cues = _read_srt(Path(ts["srt"])) if ts.get("srt") else []
        for c in cues:
            subs.append({"a": round(t + c["a"], 3), "b": round(t + c["b"], 3), "text": c["text"]})
        kind = _kind(ts, ms)
        group = (ts.get("group") or (ms or {}).get("_group") or "").strip()
        if group and group not in groups_seen:
            groups_seen.append(group)
        sl: Dict[str, Any] = {"no": ts.get("no"), "id": ts.get("data_id") or "", "kind": kind,
                              "t0": round(t, 3), "t1": round(t + dur, 3), "speech": round(au, 3),
                              "group": group, "title": (ms or {}).get("title") or ts.get("title") or ""}
        speak_end = max(1.0, au - .3) if au > 0 else dur - .5
        title_at = .35
        if kind == "cover":
            parts = [p.strip() for p in re.split(r"\s+·\s+", sl["title"]) if p.strip()]
            sl["cover"] = {"label": f"{man.get('label') or lid} · {parts[0]}" if parts else lid,
                           "big": parts[1] if len(parts) > 1 else sl["title"],
                           "items": parts[2:]}
            sl["cover"]["items_at"] = [round(t + v, 3) for v in
                                       match_times(sl["cover"]["items"], cues, 2.0, speak_end, .6)]
        elif kind == "closing":
            sl["title"] = "마무리"
            sl["bullets"] = [{"text": g, "at": round(t + v, 3)} for g, v in
                             zip(groups_seen, match_times(groups_seen, cues, 1.4, speak_end, .5))]
        elif kind == "quiz":
            card = parse_card(ms["card"])
            sl["title"] = ms.get("title") or sl["title"]
            q_at = match_times([card["q"]], cues, .8, speak_end)[0] if card["q"] else .8
            # 내레이션은 보통 지문·보기를 읽지 않는다("화면의 자료와 보기를 보면서…") → 질문 뒤 일정한 박자로, 말이 끝나기 전에 다 쓴다
            n_items = len(card["passage"]) + len(card["choices"])
            lo = q_at + 1.0
            hi = max(lo + .6 * n_items, speak_end - 1.8)
            step = min(1.6, (hi - lo) / max(1, n_items))
            seq = [lo + i * step for i in range(n_items)]
            p_at, c_at = seq[:len(card["passage"])], seq[len(card["passage"]):]
            sl["card"] = {"head": card["head"], "q": card["q"], "q_at": round(t + q_at, 3),
                          "passage": [{**p, "at": round(t + a, 3)} for p, a in zip(card["passage"], p_at)],
                          "choices": [{"text": c, "at": round(t + a, 3)} for c, a in zip(card["choices"], c_at)]}
        else:
            bl = list((ms or {}).get("bullets") or [])
            ats = match_times(bl, cues, title_at + 1.6, speak_end, .7)
            sl["bullets"] = [{"text": b, "at": round(t + a, 3)} for b, a in zip(bl, ats)]
            if kind == "answer":
                m = re.search(f"[{CIRCLED}]", sl["title"])
                sl["answer"] = CIRCLED.index(m.group(0)) + 1 if m else None
            fi = (ms or {}).get("fig")
            if fi and 0 < int(fi) <= len(figs):
                src = figs[int(fi) - 1]
                last_b = ats[-1] if ats else title_at + 1.5
                f_at = min(last_b + 1.6, max(title_at + 2.0, speak_end * .55))
                sl["fig"] = {"type": "table" if "<table" in src[:200] else "svg", "src": src,
                             "at": round(t + f_at, 3)}
        sl["title_at"] = round(t + title_at, 3)
        slides.append(sl)
        t += dur

    real = ffprobe_duration(part) if part.exists() else t
    if slides and real and abs(real - t) > 1e-3:
        slides[-1]["t1"] = round(slides[-1]["t1"] + (real - t), 3)
    return {"job": job_dir.name, "lecture": lid, "section": sid, "first": first, "last": last,
            "dur": round(real or t, 3), "slides": slides, "subs": subs, "src_part": str(part)}
