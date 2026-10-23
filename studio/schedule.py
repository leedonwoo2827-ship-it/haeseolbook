"""예약 — 올릴 회차들을 시각 칸(패턴)에 차례로 배치하고 YouTube Studio 「예약 공개」로 넘긴다.

업로드는 지금 하고 공개만 그 시각에 — PC 를 꺼도 그 시각에 공개된다(Studio 자체 예약).
이미 예약해 둔 칸(모든 회차 state.json 의 posted.scheduled_for)은 비켜 간다.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from . import JOBS
from .job import read_json

FMT = "%Y-%m-%d %H:%M"

# weekdays: 0=월 … 6=일
PATTERNS: Dict[str, Dict] = {
    "now":      {"label": "지금 바로 차례로 (예약 없이 · 공개 범위 그대로)", "now": True},
    "daily":    {"label": "매일 1편 · 정한 시각", "days": [0, 1, 2, 3, 4, 5, 6]},
    "every-12": {"label": "12시간 간격 (시작 시각부터)", "every_h": 12},
    "every-6":  {"label": "6시간 간격 (시작 시각부터)", "every_h": 6},
    "every-3":  {"label": "3시간 간격 (시작 시각부터)", "every_h": 3},
    "mwf":      {"label": "주 3편 · 월·수·금", "days": [0, 2, 4]},
    "tf":       {"label": "주 2편 · 화·금", "days": [1, 4]},
    "weekly":   {"label": "주 1편 · 시작일과 같은 요일", "weekly": True},
}
DEFAULT = "daily"


def parse_when(text: str) -> datetime:
    text = (text or "").strip().replace("T", " ")
    for f in (FMT, "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, f)
        except ValueError:
            pass
    raise ValueError(f"시각 형식은 2026-10-24 19:00 꼴이에요: {text}")


def taken(account: Optional[str] = None) -> List[str]:
    out = []
    for st_file in JOBS.glob("*/state.json"):
        p = (read_json(st_file) or {}).get("posted") or {}
        if p.get("scheduled_for") and (account is None or p.get("account") in (None, account)):
            out.append(p["scheduled_for"])
    return out


def slots(n: int, *, pattern: str = DEFAULT, start: Optional[str] = None, at: str = "19:00",
          account: Optional[str] = None) -> List[Optional[datetime]]:
    """패턴의 빈 칸 n 개. start(YYYY-MM-DD)부터, 없으면 오늘부터. Studio 는 너무 가까운 예약을 받지 않아 지금+30분 이후만."""
    p = PATTERNS.get(pattern, PATTERNS[DEFAULT])
    if p.get("now"):
        return [None] * n                   # 예약 없이 지금 차례로
    if not re.fullmatch(r"\d{1,2}:\d{2}", at or ""):
        at = "19:00"
    h, m = map(int, at.split(":"))
    busy = set(taken(account))
    earliest = datetime.now() + timedelta(minutes=30)
    t = (datetime.strptime(start, "%Y-%m-%d") if start else datetime.now()).replace(hour=h, minute=m, second=0, microsecond=0)
    if p.get("every_h"):
        step, ok = timedelta(hours=int(p["every_h"])), (lambda d: True)
    elif p.get("weekly"):
        step, ok = timedelta(days=7), (lambda d: True)
    else:
        step, ok = timedelta(days=1), (lambda d: d.weekday() in p["days"])
    out: List[datetime] = []
    for _ in range(3000):
        if t >= earliest and ok(t) and t.strftime(FMT) not in busy:
            out.append(t)
            if len(out) >= n:
                break
        t += step
    return out
