"""엑셀 수식·셀 주소·날짜·오류값 → 읽는 소리. 사전(PronunciationMap)보다 **먼저** 돈다.

왜 따로 두는가: 사전은 낱말 치환이라 `=$A2*B$1`, `[B2:D4]`, `2027-03-30`, `#,##0,,` 같은 기호열을 읽지 못한다.
여기서 기호열을 소리로 풀고, 함수명(SUM·VLOOKUP…)은 그대로 남겨 과목 사전(studio/dict/spreadsheet.yaml)이 읽게 한다.

  =$A2*B$1        → 달러 에이 이 곱하기 비 달러 일
  [B2:D4] 영역    → 비이부터 디사까지 영역
  2027-03-30      → 이천이십칠년 삼월 삼십일
  #N/A · #DIV/0!  → 샵 엔에이 · 샵 디브 제로
  F4 를 누르면    → 에프포 를 누르면 (기능키는 영어 숫자로 읽는다)

셀 주소만 덩그러니 있는 경우(`D3의 수식`)는 시트 과목에서만 바꾼다 — 컴퓨터 일반의 MP3·IPv6 를 건드리지 않게.
"""
from __future__ import annotations

import re

LETTER = {
    "A": "에이", "B": "비", "C": "씨", "D": "디", "E": "이", "F": "에프", "G": "지", "H": "에이치",
    "I": "아이", "J": "제이", "K": "케이", "L": "엘", "M": "엠", "N": "엔", "O": "오", "P": "피",
    "Q": "큐", "R": "알", "S": "에스", "T": "티", "U": "유", "V": "브이", "W": "더블유", "X": "엑스",
    "Y": "와이", "Z": "제트",
}
_D = "영일이삼사오육칠팔구"
_EN = ["", "원", "투", "쓰리", "포", "파이브", "식스", "세븐", "에이트", "나인", "텐", "일레븐", "트웰브"]
MONTH = {6: "유월", 10: "시월"}

ERRORS = {"#N/A": "샵 엔에이", "#NUM!": "샵 넘", "#VALUE!": "샵 밸류", "#DIV/0!": "샵 디브 제로",
          "#REF!": "샵 레프", "#NAME?": "샵 네임", "#NULL!": "샵 널", "#SPILL!": "샵 스필"}
OPS = {"<>": " 같지 않음 ", ">=": " 크거나 같음 ", "<=": " 작거나 같음 ", ">": " 큼 ", "<": " 작음 ",
       "=": " 같음 ", "*": " 곱하기 ", "/": " 나누기 ", "+": " 더하기 ", "-": " 빼기 ", "^": " 제곱 ",
       "&": " 앤드 ", ":": "부터 ", ",": ", ", ";": ", ", "(": " ", ")": " ", "%": " 퍼센트"}


def sino(n: int) -> str:
    """0~9999억 정수 → 한자어 수사 (십·백·천 앞 1은 생략)"""
    if n == 0:
        return "영"
    parts = []
    for gi, unit in enumerate(("", "만", "억", "조")):
        part = (n // 10000 ** gi) % 10000
        if not part:
            continue
        s = ""
        for d, u in zip(f"{part:04d}", ("천", "백", "십", "")):
            if d != "0":
                s += ("" if d == "1" and u else _D[int(d)]) + u
        parts.insert(0, ("" if unit == "만" and part == 1 else s) + unit)
    return "".join(parts)


def number(tok: str) -> str:
    """1,500 · -3.7 · 0.5 · 30% → 소리"""
    neg = tok.startswith("-")
    tok = tok.lstrip("-").replace(",", "")
    if "." in tok:
        a, b = tok.split(".", 1)
        s = sino(int(a or 0)) + " 점 " + "".join(_D[int(c)] for c in b)
    else:
        s = sino(int(tok))
    return ("마이너스 " if neg else "") + s


def cell(ref: str) -> str:
    """$A$1 → 달러 에이 달러 일, AB12 → 에이비십이"""
    m = re.fullmatch(r"(\$?)([A-Z]{1,3})(\$?)(\d+)", ref)
    if not m:
        return ref
    col = "".join(LETTER[c] for c in m.group(2))
    row = sino(int(m.group(4)))
    if m.group(1) or m.group(3):
        return " ".join(x for x in ("달러" if m.group(1) else "", col, "달러" if m.group(3) else "", row) if x)
    return col + row


_REF = r"\$?[A-Z]{1,3}\$?[1-9]\d{0,6}"
_RANGE = re.compile(rf"(?<![A-Za-z0-9$])({_REF})\s*:\s*({_REF})(?![A-Za-z0-9])")
_COLS = re.compile(r"(?<![A-Za-z0-9$])\$?([A-Z]{1,3}):\$?([A-Z]{1,3})(?![A-Za-z0-9])")
_BRACKET = re.compile(rf"\[\s*((?:{_REF})(?:\s*:\s*{_REF})?)\s*\]")
_CELL = re.compile(rf"(?<![A-Za-z0-9$#])({_REF})(?![A-Za-z0-9(])")
_FKEY = re.compile(r"(?<![A-Za-z0-9])F(1[0-2]|[1-9])(?=\s*(?:키|를|을|와|과|는|은|만|로|,|\)|$|\s*\+)|(?![0-9A-Za-z]))")
_DATE = re.compile(r"(?<!\d)(\d{4})-(\d{1,2})-(\d{1,2})(?!\d)")
_ERR = re.compile("|".join(re.escape(k) for k in sorted(ERRORS, key=len, reverse=True)))
# 수식의 시작: '=' 앞이 문장 시작·공백·여는 괄호·따옴표이고 뒤가 수식 글자. 끝은 _formula_end 가 찾는다.
_FORMULA_START = re.compile(r"(?:^|(?<=[\s(\[“\"'‘]))=(?=[A-Za-z$(\d\-\"])")
_FMT = re.compile(r"(?<![\w#])((?:[#0?]+[,.]?)+[#0?,.%]*|[#0?,.]*#[#0?,.]*)(?![#0?A-Za-z0-9])")
_NUM = re.compile(r"(?<![A-Za-z0-9.\-])-?\d{1,3}(?:,\d{3})+(?:\.\d+)?(?![\d])|(?<![A-Za-z0-9.,\-])-?\d+(?:\.\d+)?(?![\d,]|\s*(?:개|명|시간|살|마리|가지|군데|곳|줄|칸|번째))")
_TOKEN = re.compile(rf"\"[^\"]*\"|{_REF}\s*:\s*{_REF}|\$?[A-Z]{{1,3}}:\$?[A-Z]{{1,3}}(?![0-9])|{_REF}|[A-Z][A-Z0-9.]*(?=\()|TRUE|FALSE|\d+(?:\.\d+)?|<>|>=|<=|[-+*/^&=<>:,;()%]|\S")


def _date(m: re.Match) -> str:
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if not (1 <= mo <= 12 and 1 <= d <= 31):
        return m.group(0)
    return f"{sino(y)}년 {MONTH.get(mo, sino(mo) + '월')} {sino(d)}일"


def formula(expr: str) -> str:
    """수식 본문(= 뒤) → 소리. 함수명은 그대로 남긴다(사전이 읽는다)."""
    out, prev = [], ""
    for t in _TOKEN.findall(expr):
        if t.startswith('"'):
            body = t[1:-1]
            if not body:
                out.append(" 빈 문자열 ")
            elif re.match(r"[<>=]", body):          # 조건 문자열 ">=80" 은 수식처럼 읽는다
                out.append(f" {formula(body)} ")
            else:
                out.append(f" {body} ")
        elif ":" in t and re.fullmatch(rf"{_REF}\s*:\s*{_REF}", t):
            a, b = re.split(r"\s*:\s*", t)
            out.append(f" {cell(a)}부터 {cell(b)}까지 ")
        elif re.fullmatch(r"\$?[A-Z]{1,3}:\$?[A-Z]{1,3}", t):
            a, b = (x.strip("$") for x in t.split(":"))
            out.append(f" {''.join(LETTER[c] for c in a)}열부터 {''.join(LETTER[c] for c in b)}열까지 ")
        elif re.fullmatch(_REF, t):
            out.append(f" {cell(t)} ")
        elif re.fullmatch(r"\d+(?:\.\d+)?", t):
            out.append(f" {number(t)} ")
        elif t == "-" and prev in ("", "(", ",", "op"):
            out.append(" 마이너스 ")
            t = "-u"
        elif t in OPS:
            out.append(OPS[t])
            t = "op" if t not in "(),;" else t
        else:
            out.append(f" {t} ")
        prev = t if t in ("(", ",", "-u") else ("op" if t == "op" else "x")
    s = re.sub(r"\s+", " ", "".join(out)).strip()
    return re.sub(r"\s+,", ",", s)


def _fmt(m: re.Match) -> str:
    """서식 코드(#,##0,,) → 글자 단위로"""
    tok = m.group(1)
    if "#" not in tok and not re.search(r"0[,.]|[,.]0", tok):
        return tok
    name = {"#": "샵", "0": "영", "?": "물음표", ",": "쉼표", ".": "점", "%": "퍼센트"}
    return " " + " ".join(name.get(c, c) for c in tok) + " "


def speak(text: str, sheet: bool = False) -> str:
    """문장 전체에 적용. sheet=True 면 문장 속 맨 셀 주소(D3, $C2)까지 읽는다."""
    if not text:
        return text
    text = _ERR.sub(lambda m: f" {ERRORS[m.group(0)]} ", text)
    text = _formulas(text)
    text = _spans(text)
    text = _BRACKET.sub(lambda m: _ref_words(m.group(1)), text)
    text = _DATE.sub(_date, text)
    text = _FKEY.sub(lambda m: "에프" + _EN[int(m.group(1))], text)
    if sheet:
        text = _RANGE.sub(lambda m: f"{cell(m.group(1))}부터 {cell(m.group(2))}까지", text)
        text = _COLS.sub(lambda m: f"{''.join(LETTER[c] for c in m.group(1))}열부터 {''.join(LETTER[c] for c in m.group(2))}열까지", text)
        text = _CELL.sub(lambda m: cell(m.group(1)), text)
        text = _FMT.sub(_fmt, text)
        text = _NUM.sub(lambda m: number(m.group(0)), text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return re.sub(r" +([,.?!)])", r"\1", text).strip()


# 범위·기호 표시 — (가)~(다) → 가부터 다까지, ①~④ → 1번부터 4번까지, 1~20번 → 일 번부터 이십 번까지
_CIRC = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"
_MARK = r"\(([가-하ㄱ-ㅎA-Za-z])\)"
_MARK_SPAN = re.compile(rf"{_MARK}\s*[~∼～]\s*{_MARK}")
_CIRC_SPAN = re.compile(rf"([{_CIRC}])\s*[~∼～]\s*([{_CIRC}])")
_NUM_SPAN = re.compile(r"(?<![\d.,])(\d{1,4})\s*[~∼～]\s*(\d{1,4})(?![\d.,])\s*(번|회|쪽|개|장|명|년|월|일|시간|분|초|단계|과목|문항|행|열)?")
_MARK_ONE = re.compile(rf"{_MARK}(?=[은는이가을를와과의에도만로,\s]|$)")


def _spans(text: str) -> str:
    text = _MARK_SPAN.sub(lambda m: f"{m.group(1)}부터 {m.group(2)}까지", text)
    text = _CIRC_SPAN.sub(lambda m: f"{sino(_CIRC.index(m.group(1)) + 1)} 번부터 {sino(_CIRC.index(m.group(2)) + 1)} 번까지", text)

    def num(m: re.Match) -> str:
        u = m.group(3) or ""
        a, b = sino(int(m.group(1))), sino(int(m.group(2)))
        return f"{a} {u}부터 {b} {u}까지" if u else f"{a}에서 {b}"
    text = _NUM_SPAN.sub(num, text)
    return _MARK_ONE.sub(lambda m: m.group(1), text)       # (가)는 → 가는


def _formula_end(text: str, i: int) -> int:
    """text[i] 가 수식 첫 글자일 때 끝 위치 — 괄호 깊이 0 에서 공백·한글을 만나면 끝. 따옴표 안은 무엇이든 수식."""
    depth, quote, j = 0, False, i
    while j < len(text):
        c = text[j]
        if c == '"':
            quote = not quote
        elif not quote:
            if c == "(":
                depth += 1
            elif c == ")":
                if depth == 0:
                    break
                depth -= 1
            elif depth == 0 and (c.isspace() or "가" <= c <= "힣" or c in "[]"):
                break
        j += 1
    while j > i and text[j - 1] in ",.;" and depth == 0:     # 문장 부호는 수식이 아니다
        j -= 1
    return j


def _formulas(text: str) -> str:
    out, pos = [], 0
    for m in _FORMULA_START.finditer(text):
        if m.start() < pos:
            continue
        end = _formula_end(text, m.end())
        out += [text[pos:m.start()], formula(text[m.end():end])]
        pos = end
    return "".join(out) + text[pos:]


def _ref_words(ref: str) -> str:
    parts = re.split(r"\s*:\s*", ref)
    return f"{cell(parts[0])}부터 {cell(parts[1])}까지" if len(parts) == 2 else cell(parts[0])
