"""마커 소리 — 보드에 쓰이는 획마다 소리 한 토막(lemo-opuscar whiteboard mix.py 의 marker() 를 표준 라이브러리로 옮김).

    펠트가 유광 보드를 긁는 쉬익 대역(2.2–7.5kHz) + 몸통(0.5–1.5kHz), 손 속도 곡선(느리게–빠르게–느리게)으로 감싼다.
    닿는 순간의 작은 틱, 긴 선에는 가끔 끽 소리. 팬 = 획의 화면 x. numpy 없이 돈다(섹션 하나 10~30초).
"""
from __future__ import annotations

import array
import math
import random
import wave
from pathlib import Path
from typing import Any, Dict, List

SR = 48000


def _bandpass(x: List[float], f0: float, q: float) -> List[float]:
    w = 2 * math.pi * f0 / SR
    al = math.sin(w) / (2 * q)
    b0, b2, a0, a1, a2 = al, -al, 1 + al, -2 * math.cos(w), 1 - al
    b0, b2, a1, a2 = b0 / a0, b2 / a0, a1 / a0, a2 / a0
    y = [0.0] * len(x)
    x1 = x2 = y1 = y2 = 0.0
    for i, v in enumerate(x):
        o = b0 * v + b2 * x2 - a1 * y1 - a2 * y2
        x2, x1, y2, y1 = x1, v, y1, o
        y[i] = o
    return y


def _bank(rng: random.Random, sec: float, lo: float, hi: float) -> List[float]:
    n = int(sec * SR)
    f0 = math.sqrt(lo * hi)
    q = f0 / (hi - lo)
    x = _bandpass(_bandpass([rng.gauss(0, 1) for _ in range(n)], f0, q), f0, q)
    pk = max(abs(v) for v in x) or 1
    return [v / pk * 2.2 for v in x]


def render(events: List[Dict[str, Any]], dur: float, out: Path, seed: int = 11) -> int:
    """events(페이지의 window.EV) → 스테레오 16bit wav. 반환: 소리를 낸 이벤트 수."""
    rng = random.Random(seed)
    banks = {"hiss": _bank(rng, 4.0, 2200, 7500), "body": _bank(rng, 4.0, 500, 1500),
             "hiss_o": _bank(rng, 3.0, 2500, 8200), "hiss_b": _bank(rng, 3.0, 2000, 6900)}
    ns = int((dur + .5) * SR)
    L = array.array("f", bytes(4 * ns))
    Rr = array.array("f", bytes(4 * ns))
    used = 0
    for e in events:
        typ = e.get("type")
        if typ not in ("write", "stroke", "dash", "tap"):
            continue
        t0 = float(e["t"])
        if t0 >= dur:
            continue
        d = max(.03, float(e.get("dur") or .05))
        n = int(d * SR)
        i0 = int(t0 * SR)
        if i0 + n >= ns:
            n = ns - i0 - 1
        if n <= 8:
            continue
        p = min(.92, max(.08, float(e.get("sx", 960)) / 1920))
        gl, gr = math.cos(p * math.pi / 2) * 1.41, math.sin(p * math.pi / 2) * 1.41
        z = float(e.get("z", 1) or 1)
        g = .32 * min(1.3, z ** .5) * (.8 if typ == "write" else 1.0) * (.55 if typ == "tap" else 1.0)
        hb = banks["hiss" if rng.random() < .6 else ("hiss_o" if rng.random() < .5 else "hiss_b")]
        bb = banks["body"]
        j0, k0 = rng.randrange(0, len(hb) - n - 1), rng.randrange(0, len(bb) - n - 1)
        ramp_in, ramp_out = .006 * SR, .012 * SR
        dash = typ == "dash"
        tick_n = int(.004 * SR)
        for k in range(n):
            u = k / n
            v = 1.2 if dash else 1 - .8 * math.cos(2 * math.pi * u)
            a = (v / 1.8) ** .8 * min(1.0, k / ramp_in) * min(1.0, (n - k) / ramp_out)
            s = (hb[j0 + k] * (.55 + .45 * v / 1.8) + bb[k0 + k] * .45) * a
            if k < tick_n:
                s += hb[j0 + k] * (1 - k / tick_n) * 1.4
            s *= g
            L[i0 + k] += s * gl
            Rr[i0 + k] += s * gr
        # 긴 선의 끽 소리(드물게)
        if typ == "stroke" and float(e.get("len") or 0) > 140 and rng.random() < .22:
            s0 = rng.uniform(.15, .55) * d
            sd = min(d - s0, rng.uniform(.06, .16))
            if sd > .03:
                m = int(sd * SR)
                f0 = rng.uniform(1500, 2600)
                vib = rng.uniform(7, 13)
                ph = 0.0
                b0 = i0 + int(s0 * SR)
                for k in range(min(m, ns - b0 - 1)):
                    ts = k / SR
                    f = f0 * (1 + .03 * math.sin(2 * math.pi * vib * ts))
                    ph += 2 * math.pi * f / SR
                    env = math.sin(math.pi * ts / sd) ** 1.5 * .35 * g
                    sq = (math.sin(ph) + .3 * math.sin(2 * ph)) * env
                    L[b0 + k] += sq * gl
                    Rr[b0 + k] += sq * gr
        used += 1
    pk = max(max(L, default=0), -min(L, default=0), max(Rr, default=0), -min(Rr, default=0)) or 1
    sc = 32767 * .5 / pk                              # 피크 −6dBFS. 목소리 대비 크기는 믹스 단계에서 LU로 맞춘다
    pcm = array.array("h", bytes(4 * ns))
    for i in range(ns):
        pcm[2 * i] = int(L[i] * sc)
        pcm[2 * i + 1] = int(Rr[i] * sc)
    out.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    return used
