"""숫자·부호·키 조합을 읽는 소리로 — 사전(pronunciation_map)보다 먼저, 수식(formula.speak) 다음에 돈다.

2026-11-04 음성 체크에서 사용자가 고친 발음을 규칙으로 옮겼다(회귀: tests/test_numbers.py).
  01회 → 일 회 (앞자리 0 은 읽지 않는다 — 「공일」 금지)
  -20을 → 마이너스 이십을          8비트 → 팔비트 · 16진수 → 십육진수
  00010100 → 영 영 영 일 영 일 영 영  (비트열은 한 자리씩 「영」「일」)
  16진수 EC → 이 씨                ⊞+Shift+S → 윈도우 키와 시프트 S
  Ctrl+C → 컨트롤 C                20을 · 2의 보수 → 이십을 · 이의 보수
건드리지 않는 것: 1000원 · 3.5를 · 1,000을 · A1 · 3-2 · 3개(고유어 단위) · 일공공일(이미 한글)
"""
from __future__ import annotations

import re

SINO_UNITS = "번|회|강|과목|단계|장|절|점|년|월|일|층|차|쪽|퍼센트|등급|위|호|부|편|기"
_D = ["", "일", "이", "삼", "사", "오", "육", "칠", "팔", "구"]


def sino(n: int) -> str:
    if n == 0:
        return "영"
    out = []
    for val, name in ((10000, "만"), (1000, "천"), (100, "백"), (10, "십")):
        q, n = divmod(n, val)
        if q:
            out.append(("" if q == 1 and val != 10000 else (sino(q) if val == 10000 else _D[q])) + name)
    if n:
        out.append(_D[n])
    return "".join(out)


_UNIT_RE = re.compile(r"(?<![A-Za-z0-9.,])(\d+)\s*(" + SINO_UNITS + r")")
_ZERO_KO_RE = re.compile(r"(?<![공영일이삼사오육칠팔구십백천])(?:공|영)([일이삼사오육칠팔구])\s*(" + SINO_UNITS + r")")
_MINUS_RE = re.compile(r"(?<![\w)\]])[-−–](?=\d)")
_BITS_RE = re.compile(r"(?<![\d.,])([01]{4,})(?![\d.,])")
_BITS_CTX = re.compile(r"진수|비트|패리티|보수|이진")
_GLUE_RE = re.compile(r"(?<![A-Za-z0-9.,])(\d+)(진수|진법|비트|바이트)")
_PARTICLE_RE = re.compile(r"(?<![\dA-Za-z$.,])(\d+)(?![\d.,])"
                          r"(?=을|를|은|는|의|과|와|으로|로|에|도|만|까지|부터|보다|입니다|이다|이고|이며|이므로|이면|이)")
_HEX_CTX = re.compile(r"16\s*진|십육\s*진|헥사|hex", re.I)
_HEX_RE = re.compile(r"(?<![A-Za-z0-9$])(?=[0-9A-F]*[A-F])([0-9A-F]{1,8})(?![A-Za-z0-9])")
_HEX_SAY = {"A": "에이", "B": "비", "C": "씨", "D": "디", "E": "이", "F": "에프", **{str(i): d for i, d in enumerate(["영"] + _D[1:])}}
_KEY_SAY = {"shift": "시프트", "ctrl": "컨트롤", "alt": "알트", "tab": "탭", "enter": "엔터", "esc": "이에스씨",
            "delete": "딜리트", "del": "딜리트", "space": "스페이스", "home": "홈", "end": "엔드"}
_KEYS = r"(?:Shift|Ctrl|Alt|Tab|Enter|Esc|Delete|Del|Space|Home|End|F\d{1,2}|[A-Za-z0-9])(?![A-Za-z])"
_WINKEY_RE = re.compile(r"⊞\s*((?:\+\s*" + _KEYS + r"\s*)+)", re.I)
_COMBO_RE = re.compile(r"(?<![A-Za-z])(Ctrl|Alt|Shift)((?:\s*\+\s*" + _KEYS + r")+)", re.I)


def _key(k: str) -> str:
    return _KEY_SAY.get(k.lower(), k.upper() if len(k) == 1 else k)


def _winkey(m: "re.Match[str]") -> str:
    return "윈도우 키와 " + " ".join(_key(k.strip()) for k in m.group(1).split("+") if k.strip())


def _combo(m: "re.Match[str]") -> str:
    return " ".join(_key(k.strip()) for k in [m.group(1)] + m.group(2).split("+") if k.strip())


def speak_numbers(text: str) -> str:
    text = text or ""
    bits_ctx = bool(_BITS_CTX.search(text))
    text = _WINKEY_RE.sub(_winkey, text)
    text = _COMBO_RE.sub(_combo, text)
    text = _MINUS_RE.sub("마이너스 ", text)
    text = _BITS_RE.sub(lambda m: " ".join("영" if c == "0" else "일" for c in m.group(1))
                        if (m.group(1).startswith("0") or bits_ctx) else m.group(1), text)
    if _HEX_CTX.search(text):
        text = _HEX_RE.sub(lambda m: " ".join(_HEX_SAY[c] for c in m.group(1)), text)
    text = _GLUE_RE.sub(lambda m: f"{sino(int(m.group(1)))}{m.group(2)}", text)
    text = _UNIT_RE.sub(lambda m: f"{sino(int(m.group(1)))} {m.group(2)}", text)
    text = _PARTICLE_RE.sub(lambda m: sino(int(m.group(1))), text)
    return _ZERO_KO_RE.sub(r"\1 \2", text)
