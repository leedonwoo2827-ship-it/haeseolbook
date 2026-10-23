"""유튜브 계정(=이 폴더의 Chrome 프로필) 목록 — profiles/accounts.json

  {"current": "dekman", "accounts": [{"name": "dekman", "label": "dekman", "port": 9381}, …]}
계정마다 profiles/<name>/ 프로필과 디버그 포트가 따로라 여러 채널 Chrome 을 동시에 띄워도 섞이지 않는다.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from . import ROOT
from .job import read_json, write_json

PROFILES = ROOT / "profiles"
FILE = PROFILES / "accounts.json"
BASE_PORT = 9381


def _load() -> Dict[str, Any]:
    d = read_json(FILE) or {}
    accs = d.get("accounts") or [{"name": "dekman", "label": "dekman", "port": BASE_PORT}]
    return {"current": d.get("current") or accs[0]["name"], "accounts": accs}


def all_() -> List[Dict[str, Any]]:
    return _load()["accounts"]


def current() -> str:
    return _load()["current"]


def get(name: Optional[str] = None) -> Dict[str, Any]:
    d = _load()
    name = name or d["current"]
    for a in d["accounts"]:
        if a["name"] == name:
            return a
    raise ValueError(f"계정이 없습니다: {name} (있는 계정: {', '.join(a['name'] for a in d['accounts'])})")


def set_current(name: str) -> None:
    get(name)
    d = _load()
    d["current"] = name
    write_json(FILE, d)


def add(name: str, label: str = "") -> Dict[str, Any]:
    if not re.fullmatch(r"[a-z0-9_-]{2,30}", name):
        raise ValueError("계정 이름은 영소문자·숫자·-·_ 2~30자 (예: ubionbook)")
    d = _load()
    if any(a["name"] == name for a in d["accounts"]):
        raise ValueError(f"이미 있는 계정입니다: {name}")
    port = max(a["port"] for a in d["accounts"]) + 1
    acc = {"name": name, "label": label.strip() or name, "port": port}
    d["accounts"].append(acc)
    write_json(FILE, d)
    return acc


def set_label(name: str, label: str) -> None:
    d = _load()
    for a in d["accounts"]:
        if a["name"] == name:
            a["label"] = label.strip() or name
    write_json(FILE, d)
