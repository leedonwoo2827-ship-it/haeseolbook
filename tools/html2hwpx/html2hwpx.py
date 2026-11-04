"""html2hwpx — HTML → 한글(HWPX). 파이썬 표준 라이브러리만 쓴다(설치할 것 없음).

  python html2hwpx.py 입력.html [-o 출력.hwpx] [--page 188x257] [--margin 15] [--template 양식.hwpx]

무엇을 옮기는가
────────────────────────────────────────────────────────────────────────────
  h1 h2 h3 h4 p div section li pre   문단 (h* 는 굵고 크게, pre 는 줄마다 한 문단)
  b strong · small .m .muted .tg      굵게 · 작은 회색 글씨
  table tr th td (colspan)            진짜 한글 표 (th 는 굵게·옅은 회색 바탕)
  img (png jpg gif bmp)               그림 — 문단 하나에 하나, 폭은 style="width:22mm" 또는 원본 크기(본문 폭 80% 안)
  img (svg)                           같은 이름의 .png 가 옆에 있으면 그것, 없으면 Edge/Chrome 헤드리스로 PNG 로 굽는다
                                      (윈도우에는 Edge 가 늘 있다 — 그것도 없으면 그림 자리에 alt 글자)
  쪽 나눔                              <style> 의 break-before:page 규칙(.a+.a · .a.b · .a) 과 style="break-before:page"

판형은 --page(기본 188x257mm = 46배판) · --margin(mm, 기본 15). --template 을 주면 그 양식의 글꼴·스타일·쪽 설정을
그대로 쓰고(--page 를 따로 주지 않는 한) 본문만 이 HTML 로 채운다.

글꼴은 「맑은 고딕」을 더해 쓴다(--font 로 바꿈). 양식을 주면 양식의 문단 스타일을 이름으로 찾아 쓴다 —
기본 짝: 본문=*본문 · h1=*절제목 · h2=*1.제목 · h3=*(1)제목 · h4=*1)제목 · 표=*표내용 (--styles 로 바꿈, 없는 이름은 기본 모양).
양식의 바탕쪽(머리말) 글자는 --head(기본: HTML 의 <title>)로 바꾼다 — 다른 책 제목이 남지 않게.
한글이 문서를 열 때 줄·쪽 배치를 다시 계산하므로 배치 정보(linesegarray)는 쓰지 않는다.
"""
from __future__ import annotations

import argparse
import base64
import html
import io
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import zipfile
from html.parser import HTMLParser

HWPUNIT_PER_MM = 7200 / 25.4
PX_HWP = 75                     # 96dpi 1px = 75 HWPUNIT (한글이 그림 원본 크기를 이렇게 잡는다)

# ─────────────────────────────────────────────────────────────────────────────
# HTML → 블록
# ─────────────────────────────────────────────────────────────────────────────

BLOCK = {"h1", "h2", "h3", "h4", "h5", "p", "div", "section", "article", "header", "footer", "li", "ul", "ol",
         "pre", "table", "blockquote", "figure", "main", "body", "html", "aside", "nav"}
SKIP = {"script", "style", "head", "title", "meta", "link", "svg", "noscript"}
VOID = {"br", "img", "meta", "link", "hr", "input", "col", "source"}
SMALL_CLASSES = {"m", "muted", "tg", "small", "note", "caption"}


class Node:
    __slots__ = ("tag", "attrs", "kids", "parent")

    def __init__(self, tag, attrs=None, parent=None):
        self.tag, self.attrs, self.kids, self.parent = tag, dict(attrs or {}), [], parent

    @property
    def classes(self):
        return set((self.attrs.get("class") or "").split())


class _Tree(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("#root")
        self.cur = self.root
        self.style = []

    def handle_starttag(self, tag, attrs):
        n = Node(tag, attrs, self.cur)
        self.cur.kids.append(n)
        if tag not in VOID:
            self.cur = n

    def handle_startendtag(self, tag, attrs):
        self.cur.kids.append(Node(tag, attrs, self.cur))

    def handle_endtag(self, tag):
        n = self.cur
        while n is not self.root and n.tag != tag:
            n = n.parent
        if n is not self.root:
            self.cur = n.parent

    def handle_data(self, data):
        if self.cur.tag == "style":
            self.style.append(data)
        self.cur.kids.append(data)


def _break_rules(css: str):
    """break-before:page 가 걸린 선택자 → [(클래스 집합, 앞에 같은 형제가 있어야 하는지)]"""
    rules = []
    for sel, body in re.findall(r"([^{}]+)\{([^}]*)\}", css):
        if not re.search(r"(page-)?break-before\s*:\s*(page|always)", body):
            continue
        for one in sel.split(","):
            last = one.strip().split()[-1] if one.strip() else ""
            sib = "+" in last
            comp = last.split("+")[-1]
            cls = set(re.findall(r"\.([\w-]+)", comp))
            if cls:
                rules.append((cls, sib))
    return rules


class Run:
    __slots__ = ("text", "style")

    def __init__(self, text, style):
        self.text, self.style = text, style


class Builder:
    """트리를 훑어 블록 목록을 만든다: ("p", runs, pstyle, brk) · ("tbl", rows, brk) · ("img", path, w, h, brk)"""

    def __init__(self, base_dir, rules, text_w_hwp, svg_tool):
        self.base, self.rules, self.text_w, self.svg_tool = base_dir, rules, text_w_hwp, svg_tool
        self.blocks, self.pending_break, self.carry = [], False, []
        self.tmp = tempfile.mkdtemp(prefix="html2hwpx-")

    # ── 쪽 나눔 ──
    def _breaks(self, n: Node) -> bool:
        st = (n.attrs.get("style") or "").replace(" ", "")
        if "break-before:page" in st or "page-break-before:always" in st:
            return True
        cl = n.classes
        for cls, sib in self.rules:
            if cls <= cl:
                if not sib:
                    return True
                prev = [k for k in n.parent.kids if isinstance(k, Node)] if n.parent else []
                i = prev.index(n)
                if i > 0 and cls <= prev[i - 1].classes:
                    return True
        return False

    # ── 걷기 ──
    def walk(self, n: Node, style="normal", pstyle="body"):
        if isinstance(n, str) or n.tag in SKIP:
            return
        if self._breaks(n):
            self.pending_break = True
        tag = n.tag
        if tag in ("h1", "h2", "h3", "h4", "h5"):
            style = pstyle = tag if tag != "h5" else "h4"
        if "ex" in n.classes or tag in ("blockquote", "li"):
            pstyle = "indent" if pstyle == "body" else pstyle
        if tag == "table":
            return self._table(n)
        if tag == "pre":
            for line in _text(n).split("\n"):
                self._para([Run(line, "code")], "indent" if pstyle == "indent" else "body")
            return
        if tag == "img":
            return self._img(n)
        # 인라인만 가진 블록 → 문단 하나 (중간의 블록·그림은 끊어서)
        runs = []
        for k in n.kids:
            if isinstance(k, str):
                t = re.sub(r"\s+", " ", k)
                if t.strip() or (runs and t == " "):
                    runs.append(Run(t, style))
            elif k.tag in SKIP:
                continue
            elif k.tag == "br":
                self._para(runs, pstyle)
                runs = []
            elif k.tag in BLOCK or k.tag == "img" or _has_block(k):
                # 「1.」 처럼 짧은 머리 글자 뒤에 블록이 오면(번호 + 발문) 그 블록의 첫 문단 앞에 붙인다
                label = "".join(r.text for r in runs).strip()
                if label and len(label) <= 8 and k.tag not in ("img", "table"):
                    self.carry = [r for r in runs if r.text] + [Run(" ", "normal")]
                else:
                    self._para(runs, pstyle)
                runs = []
                self.walk(k, style, pstyle)
            else:
                runs += self._inline(k, style)
        self._para(runs, pstyle)

    def _inline(self, n: Node, style):
        if n.tag in SKIP:
            return []
        if n.tag in ("b", "strong") or "ans" in n.classes or "no" in n.classes:
            style = "bold" if style in ("normal", "small") else style
        if n.tag == "small" or n.classes & SMALL_CLASSES:
            style = "small"
        if n.tag == "code":
            style = "code" if style == "normal" else style
        out = []
        for k in n.kids:
            if isinstance(k, str):
                out.append(Run(re.sub(r"\s+", " ", k), style))
            elif k.tag != "br":
                out += self._inline(k, style)
        # 번호 칸(① · 1. · 정답 ③)은 CSS 로 띄워 두는 일이 많다 — 글자로는 한 칸 띄운다
        if out and (n.classes & {"c", "no", "num", "ans"} or (n.parent and n.parent.classes & {"ah"})):
            out.append(Run(" ", "normal"))
        return out

    def _para(self, runs, pstyle):
        if self.carry and any(r.text.strip() for r in runs):
            runs, self.carry = self.carry + runs, []
        runs = [r for r in runs if r.text]
        if runs:
            runs[0].text = runs[0].text.lstrip()
            runs[-1].text = runs[-1].text.rstrip()
        if not any(r.text.strip() for r in runs):
            return
        self.blocks.append(("p", runs, pstyle, self._take_break()))

    def _take_break(self):
        b, self.pending_break = self.pending_break, False
        return b

    # ── 표 ──
    def _table(self, n: Node):
        rows = []
        for tr in _find(n, "tr"):
            cells = []
            for td in [k for k in tr.kids if isinstance(k, Node) and k.tag in ("td", "th")]:
                head = td.tag == "th"
                cells.append({"text": re.sub(r"\s+", " ", _text(td)).strip(), "head": head,
                              "span": max(1, int(td.attrs.get("colspan") or 1))})
            if cells:
                rows.append(cells)
        if rows:
            self.blocks.append(("tbl", rows, self._take_break()))

    # ── 그림 ──
    def _img(self, n: Node):
        src = html.unescape(n.attrs.get("src") or "")
        alt = n.attrs.get("alt") or ""
        path = os.path.normpath(os.path.join(self.base, src)) if src and not re.match(r"^\w+:", src) else ""
        png = None
        if path and os.path.isfile(path):
            ext = os.path.splitext(path)[1].lower()
            if ext in (".png", ".jpg", ".jpeg", ".gif", ".bmp"):
                png = path
            elif ext == ".svg":
                side = os.path.splitext(path)[0] + ".png"
                png = side if os.path.isfile(side) else _svg_to_png(path, self.tmp, self.svg_tool)
        if not png:
            if alt:
                self._para([Run(f"[그림: {alt}]", "small")], "body")
            return
        pw, ph, dpi_scale = _img_size(png)
        w = _css_mm(n.attrs.get("style") or "", "width") or _css_mm(n.attrs.get("width") or "", None)
        if w:
            dw = int(w * HWPUNIT_PER_MM)
        else:
            dw = int(pw * PX_HWP / dpi_scale)
            dw = min(dw, int(self.text_w * 0.8))
        dh = int(dw * ph / pw)
        self.blocks.append(("img", png, dw, dh, (pw, ph), self._take_break()))


def _has_block(n):
    return any(isinstance(k, Node) and (k.tag in BLOCK or k.tag == "img" or _has_block(k)) for k in n.kids)


def _find(n, tag):
    out = []
    for k in n.kids:
        if isinstance(k, Node):
            if k.tag == tag:
                out.append(k)
            elif k.tag != "table":
                out += _find(k, tag)
    return out


def _text(n):
    if isinstance(n, str):
        return n
    if n.tag in SKIP:
        return ""
    if n.tag == "br":
        return "\n"
    return "".join(_text(k) for k in n.kids)


def _css_mm(style, prop):
    m = re.search((rf"{prop}\s*:\s*" if prop else r"^\s*") + r"([\d.]+)\s*(mm|px|cm)?", style)
    if not m:
        return None
    v, u = float(m.group(1)), m.group(2) or "px"
    return v if u == "mm" else v * 10 if u == "cm" else v * 25.4 / 96


def _img_size(path):
    """(가로px, 세로px, 배율) — 헤드리스로 2배로 구운 SVG 는 배율 2"""
    with open(path, "rb") as f:
        head = f.read(32)
        if head[:8] == b"\x89PNG\r\n\x1a\n":
            w, h = struct.unpack(">II", head[16:24])
        elif head[:2] == b"\xff\xd8":
            f.seek(2)
            w = h = 0
            while True:
                b = f.read(1)
                while b and b != b"\xff":
                    b = f.read(1)
                b = f.read(1)
                if not b or b in (b"\xd9", b"\xda"):
                    break
                ln = struct.unpack(">H", f.read(2))[0]
                if b[0] in (0xC0, 0xC1, 0xC2):
                    f.read(1)
                    h, w = struct.unpack(">HH", f.read(4))
                    break
                f.read(ln - 2)
        elif head[:3] == b"GIF":
            w, h = struct.unpack("<HH", head[6:10])
        elif head[:2] == b"BM":
            w, h = struct.unpack("<ii", head[18:26])
        else:
            w, h = 400, 300
    return max(1, w), max(1, abs(h)), (2 if path.endswith(".@2x.png") else 1)


def _browser():
    cands = [shutil.which("msedge"), shutil.which("chrome"),
             os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
             os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
             os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
             os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe")]
    return next((c for c in cands if c and os.path.isfile(c)), None)


def _svg_to_png(svg_path, tmp, tool):
    """SVG → PNG (2배). 브라우저 헤드리스 스크린샷 — 크기는 viewBox/width·height 에서"""
    if not tool:
        return None
    s = open(svg_path, encoding="utf-8", errors="replace").read()
    m = re.search(r'viewBox\s*=\s*"[\d.\-]+[ ,]+[\d.\-]+[ ,]+([\d.]+)[ ,]+([\d.]+)"', s)
    if m:
        w, h = float(m.group(1)), float(m.group(2))
    else:
        mw, mh = re.search(r'width\s*=\s*"([\d.]+)', s), re.search(r'height\s*=\s*"([\d.]+)', s)
        w, h = (float(mw.group(1)) if mw else 600), (float(mh.group(1)) if mh else 400)
    w, h = int(round(w)), int(round(h))
    page = os.path.join(tmp, os.path.basename(svg_path) + ".html")
    with open(page, "w", encoding="utf-8") as f:
        f.write(f'<!doctype html><meta charset="utf-8"><style>html,body{{margin:0;background:#fff}}'
                f'img{{display:block;width:{w}px;height:{h}px}}</style>'
                f'<img src="file:///{svg_path.replace(os.sep, "/")}">')
    out = os.path.join(tmp, os.path.splitext(os.path.basename(svg_path))[0] + ".@2x.png")
    prof = os.path.join(tmp, "profile")
    try:
        subprocess.run([tool, "--headless=new", "--disable-gpu", "--hide-scrollbars", f"--user-data-dir={prof}",
                        "--force-device-scale-factor=2", f"--window-size={w},{h}", f"--screenshot={out}",
                        "file:///" + page.replace(os.sep, "/")],
                       capture_output=True, timeout=60)
    except Exception:          # noqa: BLE001
        return None
    return out if os.path.isfile(out) else None


# ─────────────────────────────────────────────────────────────────────────────
# HWPX 쓰기
# ─────────────────────────────────────────────────────────────────────────────

NS = ('xmlns:ha="http://www.hancom.co.kr/hwpml/2011/app" xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph" '
      'xmlns:hp10="http://www.hancom.co.kr/hwpml/2016/paragraph" xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" '
      'xmlns:hc="http://www.hancom.co.kr/hwpml/2011/core" xmlns:hh="http://www.hancom.co.kr/hwpml/2011/head" '
      'xmlns:hhs="http://www.hancom.co.kr/hwpml/2011/history" xmlns:hm="http://www.hancom.co.kr/hwpml/2011/master-page" '
      'xmlns:hpf="http://www.hancom.co.kr/schema/2011/hpf" xmlns:dc="http://purl.org/dc/elements/1.1/" '
      'xmlns:opf="http://www.idpf.org/2007/opf/" xmlns:ooxmlchart="http://www.hancom.co.kr/hwpml/2016/ooxmlchart" '
      'xmlns:hwpunitchar="http://www.hancom.co.kr/hwpml/2016/HwpUnitChar" xmlns:epub="http://www.idpf.org/2007/ops" '
      'xmlns:config="urn:oasis:names:tc:opendocument:xmlns:config:1.0"')

# 글자 모양: 이름 → (크기 pt, 굵게, 색)
CHAR = {"normal": (10, False, "#000000"), "bold": (10, True, "#000000"), "small": (8.5, False, "#666666"),
        "code": (9.5, False, "#333333"), "h1": (16, True, "#000000"), "h2": (13, True, "#000000"),
        "h3": (11.5, True, "#000000"), "h4": (10.5, True, "#000000"), "cell": (9.5, False, "#000000"),
        "cellb": (9.5, True, "#000000")}
# 문단 모양: 이름 → (정렬, 왼쪽 여백 mm, 위 pt, 아래 pt, 줄간격 %)
PARA = {"body": ("JUSTIFY", 0, 0, 3, 160), "indent": ("JUSTIFY", 7, 0, 3, 160),
        "h1": ("LEFT", 0, 10, 6, 140), "h2": ("LEFT", 0, 8, 4, 140), "h3": ("LEFT", 0, 6, 3, 140), "h4": ("LEFT", 0, 4, 2, 140),
        "cell": ("CENTER", 0, 0, 0, 130), "pic": ("LEFT", 0, 2, 4, 100)}
# 양식 스타일 짝 — 우리 이름 → 양식 문단 스타일 이름 (양식에 없으면 기본 모양)
STYLES = {"body": "*본문", "h1": "*절제목", "h2": "*1.제목", "h3": "*(1)제목", "h4": "*1)제목", "cell": "*표내용"}
# 글자 모양이 어느 문단 스타일의 글자를 본뜨는지
CHAR_BASE = {"normal": "body", "bold": "body", "small": "body", "code": "body", "h1": "h1", "h2": "h2", "h3": "h3",
             "h4": "h4", "cell": "cell", "cellb": "cell"}
PARA_BASE = {"body": "body", "indent": "body", "h1": "h1", "h2": "h2", "h3": "h3", "h4": "h4", "cell": "cell", "pic": "body"}


def find_styles(header: str, names: dict) -> dict:
    """{우리 이름: (style id, paraPr id, charPr id)} — 양식에 그 이름의 문단 스타일이 있을 때만"""
    out = {}
    for k, nm in names.items():
        m = re.search(r'<hh:style id="(\d+)" type="PARA" name="' + re.escape(nm) + r'"[^>]*?paraPrIDRef="(\d+)" charPrIDRef="(\d+)"', header)
        if m:
            out[k] = tuple(int(x) for x in m.groups())
    return out


def _attr_cnt(xml, tag, extra):
    m = re.search(rf'<hh:{tag} itemCnt="(\d+)"', xml)
    return xml.replace(m.group(0), f'<hh:{tag} itemCnt="{int(m.group(1)) + extra}"', 1), int(m.group(1))


def _add_font(header, face):
    """언어 묶음마다 글꼴 하나를 더하고 그 id(묶음 안 번호)를 돌려준다"""
    ids = []

    def repl(m):
        n = int(m.group(2))
        ids.append(n)
        font = (f'<hh:font id="{n}" face="{html.escape(face)}" type="TTF" isEmbedded="0"><hh:typeInfo familyType="FCAT_GOTHIC" '
                f'weight="6" proportion="4" contrast="0" strokeVariation="1" armStyle="1" letterform="1" midline="1" xHeight="1"/></hh:font>')
        body = m.group(3)
        return f'{m.group(1)}fontCnt="{n + 1}">{body}{font}</hh:fontface>'
    header = re.sub(r'(<hh:fontface lang="\w+" )fontCnt="(\d+)">(.*?)</hh:fontface>', repl, header, flags=re.S)
    return header, (ids[0] if ids and len(set(ids)) == 1 else None)


def build_header(header: str, font: str | None, styles: dict | None = None):
    """양식 header.xml 에 글자·문단 모양과 표 테두리를 더한다 → (header, {이름: id})

    styles 가 있으면(양식 모드) 그 스타일의 글자·문단 모양을 본떠 크기·정렬은 양식 것을 그대로 두고
    굵기·색·들여쓰기 같은 우리 쪽 차이만 얹는다."""
    styles = styles or {}
    header, fid = _add_font(header, font) if font else (header, None)
    ids = {"char": {}, "para": {}, "bf": {}, "style": {}}
    for k, (sid, _, _) in styles.items():
        ids["style"][k] = sid
    ids["style"]["indent"] = ids["style"].get("body", 0)
    # 테두리: 표 칸(실선) · 머리 칸(실선 + 옅은 바탕)
    header, nbf = _attr_cnt(header, "borderFills", 2)
    line = '<hh:{s}Border type="SOLID" width="0.12 mm" color="#7F7F7F"/>'
    sides = "".join(line.format(s=s) for s in ("left", "right", "top", "bottom"))
    bfs = ""
    for k, fill in (("cell", ""), ("head", '<hc:fillBrush><hc:winBrush faceColor="#F2F2F2" hatchColor="#999999" alpha="0"/></hc:fillBrush>')):
        nbf += 1
        ids["bf"][k] = nbf
        bfs += (f'<hh:borderFill id="{nbf}" threeD="0" shadow="0" centerLine="NONE" breakCellSeparateLine="0">'
                f'<hh:slash type="NONE" Crooked="0" isCounter="0"/><hh:backSlash type="NONE" Crooked="0" isCounter="0"/>'
                f'{sides}<hh:diagonal type="SOLID" width="0.1 mm" color="#000000"/>{fill}</hh:borderFill>')
    header = header.replace("</hh:borderFills>", bfs + "</hh:borderFills>", 1)
    # 글자 모양: 0번을 본떠 크기·굵기·색·글꼴만 바꾼다
    def char_xml(cid):
        return re.search(rf'<hh:charPr id="{cid}".*?</hh:charPr>', header, re.S).group(0)

    header, nc = _attr_cnt(header, "charProperties", len(CHAR))
    out = ""
    for i, (k, (pt, bold, color)) in enumerate(CHAR.items()):
        st = styles.get(CHAR_BASE[k])
        base_c = char_xml(st[2] if st else 0)
        c = re.sub(r'id="\d+"', f'id="{nc + i}"', base_c, count=1)
        if st:                                   # 양식 크기를 기준으로 — 작은 글씨만 85%
            h0 = int(re.search(r'height="(\d+)"', c).group(1))
            if k == "small":
                c = re.sub(r'height="\d+"', f'height="{int(h0 * 0.85)}"', c, count=1)
                c = re.sub(r'textColor="[^"]*"', 'textColor="#555555"', c, count=1)
        else:
            c = re.sub(r'height="\d+"', f'height="{int(pt * 100)}"', c, count=1)
            c = re.sub(r'textColor="[^"]*"', f'textColor="{color}"', c, count=1)
        if fid is not None:
            c = re.sub(r'<hh:fontRef [^>]*/>', '<hh:fontRef ' + " ".join(
                f'{lang}="{fid}"' for lang in ("hangul", "latin", "hanja", "japanese", "other", "symbol", "user")) + '/>', c, count=1)
        if not (st and k.startswith("h")):          # 양식 제목은 양식 굵기 그대로
            c = re.sub(r"<hh:bold/>|<hh:italic/>", "", c)
        if bold and "<hh:bold/>" not in c:
            c = c.replace("<hh:underline", "<hh:bold/><hh:underline", 1)
        ids["char"][k] = nc + i
        out += c
    header = header.replace("</hh:charProperties>", out + "</hh:charProperties>", 1)
    # 문단 모양: 0번을 본떠 정렬·여백·간격만
    header, npp = _attr_cnt(header, "paraProperties", len(PARA))
    out = ""
    for i, (k, (align, left_mm, prev_pt, next_pt, ls)) in enumerate(PARA.items()):
        st = styles.get(PARA_BASE[k])
        base_p = re.search(rf'<hh:paraPr id="{st[1] if st else 0}".*?</hh:paraPr>', header, re.S).group(0)
        p = re.sub(r'id="\d+"', f'id="{npp + i}"', base_p, count=1)
        if not st or k in ("cell", "pic"):
            p = re.sub(r'<hh:align horizontal="\w+"', f'<hh:align horizontal="{align}"', p, count=1)
        if not st:
            p = re.sub(r'<hc:prev value="-?\d+"', f'<hc:prev value="{int(prev_pt * 100)}"', p)
            p = re.sub(r'<hc:next value="-?\d+"', f'<hc:next value="{int(next_pt * 100)}"', p)
            p = re.sub(r'<hh:lineSpacing type="\w+" value="\d+"', f'<hh:lineSpacing type="PERCENT" value="{ls}"', p)
        if not st or k == "indent":
            left0 = int(re.search(r'<hc:left value="(-?\d+)"', p).group(1)) if st else 0
            p = re.sub(r'<hc:left value="-?\d+"', f'<hc:left value="{left0 + int(left_mm * HWPUNIT_PER_MM)}"', p)
        if k == "pic":
            p = re.sub(r'<hc:intent value="-?\d+"', '<hc:intent value="0"', p)
        if k.startswith("h"):
            p = re.sub(r'keepWithNext="\d"', 'keepWithNext="1"', p, count=1)
        ids["para"][k] = npp + i
        out += p
    header = header.replace("</hh:paraProperties>", out + "</hh:paraProperties>", 1)
    return header, ids


def _esc(t):
    return html.escape(t, quote=False)


class SectionWriter:
    def __init__(self, ids, text_w):
        self.ids, self.text_w, self.out, self.images, self._oid = ids, text_w, [], [], 1900000000

    def _id(self):
        self._oid += 1
        return self._oid

    def para(self, runs, pstyle, brk, style_override=None):
        pid = self.ids["para"][pstyle]
        rs = "".join(f'<hp:run charPrIDRef="{self.ids["char"][style_override or _cstyle(r.style, pstyle)]}"><hp:t>{_esc(r.text)}</hp:t></hp:run>'
                     for r in runs)
        sid = self.ids["style"].get(pstyle, 0)
        return f'<hp:p id="0" paraPrIDRef="{pid}" styleIDRef="{sid}" pageBreak="{int(brk)}" columnBreak="0" merged="0">{rs}</hp:p>'

    def add_para(self, runs, pstyle, brk):
        self.out.append(self.para(runs, pstyle, brk))

    def add_table(self, rows, brk):
        cols = max(sum(c["span"] for c in r) for r in rows)
        width = int(self.text_w) - 600
        cw = width // cols
        tid = self._id()
        trs = []
        for ri, r in enumerate(rows):
            tcs, ci = [], 0
            for c in r:
                span = min(c["span"], cols - ci)
                bf = self.ids["bf"]["head" if c["head"] else "cell"]
                p = self.para([Run(c["text"], "cellb" if c["head"] else "cell")], "cell", False,
                              style_override="cellb" if c["head"] else "cell") if c["text"] else \
                    f'<hp:p id="0" paraPrIDRef="{self.ids["para"]["cell"]}" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0"><hp:run charPrIDRef="{self.ids["char"]["cell"]}"/></hp:p>'
                tcs.append(
                    f'<hp:tc name="" header="{int(c["head"] and ri == 0)}" hasMargin="0" protect="0" editable="0" dirty="0" borderFillIDRef="{bf}">'
                    f'<hp:subList id="" textDirection="HORIZONTAL" lineWrap="BREAK" vertAlign="CENTER" linkListIDRef="0" linkListNextIDRef="0" '
                    f'textWidth="0" textHeight="0" hasTextRef="0" hasNumRef="0">{p}</hp:subList>'
                    f'<hp:cellAddr colAddr="{ci}" rowAddr="{ri}"/><hp:cellSpan colSpan="{span}" rowSpan="1"/>'
                    f'<hp:cellSz width="{cw * span}" height="1000"/><hp:cellMargin left="283" right="283" top="85" bottom="85"/></hp:tc>')
                ci += span
            while ci < cols:                       # 모자란 칸은 빈 칸으로 채운다(한글은 칸 수가 맞아야 연다)
                tcs.append(
                    f'<hp:tc name="" header="0" hasMargin="0" protect="0" editable="0" dirty="0" borderFillIDRef="{self.ids["bf"]["cell"]}">'
                    f'<hp:subList id="" textDirection="HORIZONTAL" lineWrap="BREAK" vertAlign="CENTER" linkListIDRef="0" linkListNextIDRef="0" '
                    f'textWidth="0" textHeight="0" hasTextRef="0" hasNumRef="0"><hp:p id="0" paraPrIDRef="{self.ids["para"]["cell"]}" styleIDRef="0" '
                    f'pageBreak="0" columnBreak="0" merged="0"><hp:run charPrIDRef="{self.ids["char"]["cell"]}"/></hp:p></hp:subList>'
                    f'<hp:cellAddr colAddr="{ci}" rowAddr="{ri}"/><hp:cellSpan colSpan="1" rowSpan="1"/>'
                    f'<hp:cellSz width="{cw}" height="1000"/><hp:cellMargin left="283" right="283" top="85" bottom="85"/></hp:tc>')
                ci += 1
            trs.append("<hp:tr>" + "".join(tcs) + "</hp:tr>")
        tbl = (f'<hp:tbl id="{tid}" zOrder="0" numberingType="TABLE" textWrap="TOP_AND_BOTTOM" textFlow="BOTH_SIDES" lock="0" '
               f'dropcapstyle="None" pageBreak="CELL" repeatHeader="1" rowCnt="{len(rows)}" colCnt="{cols}" cellSpacing="0" '
               f'borderFillIDRef="{self.ids["bf"]["cell"]}" noAdjust="0">'
               f'<hp:sz width="{cw * cols}" widthRelTo="ABSOLUTE" height="{1000 * len(rows)}" heightRelTo="ABSOLUTE" protect="0"/>'
               f'<hp:pos treatAsChar="0" affectLSpacing="0" flowWithText="1" allowOverlap="0" holdAnchorAndSO="0" vertRelTo="PARA" '
               f'horzRelTo="COLUMN" vertAlign="TOP" horzAlign="LEFT" vertOffset="0" horzOffset="0"/>'
               f'<hp:outMargin left="0" right="0" top="141" bottom="283"/><hp:inMargin left="283" right="283" top="85" bottom="85"/>'
               + "".join(trs) + "</hp:tbl>")
        self.out.append(f'<hp:p id="0" paraPrIDRef="{self.ids["para"]["body"]}" styleIDRef="0" pageBreak="{int(brk)}" columnBreak="0" merged="0">'
                        f'<hp:run charPrIDRef="{self.ids["char"]["normal"]}">{tbl}<hp:t/></hp:run></hp:p>')

    def add_image(self, path, w, h, px, brk):
        n = len(self.images) + 1
        ext = os.path.splitext(path)[1].lower().lstrip(".").replace("jpeg", "jpg")
        if ext not in ("png", "jpg", "gif", "bmp"):
            ext = "png"
        item = f"hx{n}"
        self.images.append((item, path, ext))
        ow, oh = px[0] * PX_HWP, px[1] * PX_HWP
        sx, sy = w / ow, h / oh
        pic = (f'<hp:pic id="{self._id()}" zOrder="{n}" numberingType="PICTURE" textWrap="TOP_AND_BOTTOM" textFlow="BOTH_SIDES" lock="0" '
               f'dropcapstyle="None" href="" groupLevel="0" instid="{self._id()}" reverse="0">'
               f'<hp:offset x="0" y="0"/><hp:orgSz width="{ow}" height="{oh}"/><hp:curSz width="{w}" height="{h}"/>'
               f'<hp:flip horizontal="0" vertical="0"/><hp:rotationInfo angle="0" centerX="{w // 2}" centerY="{h // 2}" rotateimage="1"/>'
               f'<hp:renderingInfo><hc:transMatrix e1="1" e2="0" e3="0" e4="0" e5="1" e6="0"/>'
               f'<hc:scaMatrix e1="{sx:.6f}" e2="0" e3="0" e4="0" e5="{sy:.6f}" e6="0"/>'
               f'<hc:rotMatrix e1="1" e2="0" e3="0" e4="0" e5="1" e6="0"/></hp:renderingInfo>'
               f'<hp:imgRect><hc:pt0 x="0" y="0"/><hc:pt1 x="{ow}" y="0"/><hc:pt2 x="{ow}" y="{oh}"/><hc:pt3 x="0" y="{oh}"/></hp:imgRect>'
               f'<hp:imgClip left="0" right="{ow}" top="0" bottom="{oh}"/><hp:inMargin left="0" right="0" top="0" bottom="0"/>'
               f'<hp:imgDim dimwidth="{ow}" dimheight="{oh}"/>'
               f'<hc:img binaryItemIDRef="{item}" bright="0" contrast="0" effect="REAL_PIC" alpha="0"/><hp:effects/>'
               f'<hp:sz width="{w}" widthRelTo="ABSOLUTE" height="{h}" heightRelTo="ABSOLUTE" protect="0"/>'
               f'<hp:pos treatAsChar="1" affectLSpacing="0" flowWithText="1" allowOverlap="0" holdAnchorAndSO="0" vertRelTo="PARA" '
               f'horzRelTo="COLUMN" vertAlign="TOP" horzAlign="LEFT" vertOffset="0" horzOffset="0"/>'
               f'<hp:outMargin left="0" right="0" top="0" bottom="0"/><hp:shapeComment>{_esc(os.path.basename(path))}</hp:shapeComment></hp:pic>')
        self.out.append(f'<hp:p id="0" paraPrIDRef="{self.ids["para"]["pic"]}" styleIDRef="0" pageBreak="{int(brk)}" columnBreak="0" merged="0">'
                        f'<hp:run charPrIDRef="{self.ids["char"]["normal"]}">{pic}<hp:t/></hp:run></hp:p>')


def _cstyle(style, pstyle):
    return style if style in CHAR else "normal"


def _page(sec0: str, page, margin_mm):
    """양식 첫 문단의 secPr 에서 쪽 크기·여백만 바꾼다"""
    if page:
        w, h = (int(x * HWPUNIT_PER_MM) for x in page)
        sec0 = re.sub(r'<hp:pagePr landscape="\w+" width="\d+" height="\d+"',
                      f'<hp:pagePr landscape="WIDELY" width="{w}" height="{h}"', sec0, count=1)
    if margin_mm is not None:
        m = int(margin_mm * HWPUNIT_PER_MM)
        sec0 = re.sub(r'<hp:margin header="\d+" footer="\d+" gutter="\d+" left="\d+" right="\d+" top="\d+" bottom="\d+"/>',
                      f'<hp:margin header="0" footer="{int(8 * HWPUNIT_PER_MM)}" gutter="0" left="{m}" right="{m}" top="{m}" bottom="{m}"/>',
                      sec0, count=1)
    return sec0


def _text_width(sec0):
    m = re.search(r'<hp:pagePr [^>]*width="(\d+)"', sec0)
    mm = re.search(r'<hp:margin [^>]*left="(\d+)" right="(\d+)"', sec0)
    return int(m.group(1)) - int(mm.group(1)) - int(mm.group(2))


def convert(src_html: str, out_hwpx: str, page=(188, 257), margin_mm=15.0, template: str | None = None,
            font: str | None = "맑은 고딕", styles: dict | None = None, head: str | None = None) -> dict:
    base = zipfile.ZipFile(template) if template else zipfile.ZipFile(io.BytesIO(base64.b64decode(BASE_HWPX)))
    files = {i.filename: base.read(i.filename) for i in base.infolist()}
    header = files["Contents/header.xml"].decode("utf-8")
    sec_xml = files["Contents/section0.xml"].decode("utf-8")
    # 첫 문단의 secPr·colPr 만 남긴다
    m = re.search(r'<hp:p [^>]*>\s*<hp:run [^>]*>\s*(<hp:secPr.*?</hp:secPr>.*?</hp:ctrl>)', sec_xml, re.S)
    secpr = m.group(1)
    secpr = _page(secpr, page if page != "keep" else None, margin_mm)
    text_w = _text_width(secpr)

    found = find_styles(header, {**STYLES, **(styles or {})}) if template else {}
    header, ids = build_header(header, font, found)

    with open(src_html, encoding="utf-8") as f:
        src = f.read()
    t = _Tree()
    t.feed(src)
    rules = _break_rules("".join(t.style))
    b = Builder(os.path.dirname(os.path.abspath(src_html)), rules, text_w, _browser())
    body = next((k for k in _all(t.root) if isinstance(k, Node) and k.tag == "body"), t.root)
    b.walk(body)

    w = SectionWriter(ids, text_w)
    first = f'<hp:p id="0" paraPrIDRef="{ids["para"]["body"]}" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0"><hp:run charPrIDRef="{ids["char"]["normal"]}">{secpr}</hp:run></hp:p>'
    counts = {"p": 0, "tbl": 0, "img": 0}
    for blk in b.blocks:
        counts[blk[0]] += 1
        if blk[0] == "p":
            w.add_para(blk[1], blk[2], blk[3])
        elif blk[0] == "tbl":
            w.add_table(blk[1], blk[2])
        else:
            w.add_image(blk[1], blk[2], blk[3], blk[4], blk[5])
    section = f'<?xml version="1.0" encoding="UTF-8" standalone="yes" ?><hs:sec {NS}>' + first + "".join(w.out) + "</hs:sec>"

    title = re.search(r"<title>(.*?)</title>", src, re.S)
    head = head if head is not None else (html.unescape(title.group(1).strip()) if title else "")
    # 바탕쪽(머리말·꼬리말)의 글자 → 이 문서 제목 (쪽 번호 같은 자동 필드는 글자가 아니라 그대로 남는다)
    for name in [n for n in files if re.match(r"Contents/masterpage\d+\.xml$", n)]:
        files[name] = re.sub(r"<hp:t>[^<]+</hp:t>", f"<hp:t>{_esc(head)}</hp:t>", files[name].decode("utf-8"), count=1).encode("utf-8")
    # 양식 그림은 바탕쪽·머리에서 쓰는 것만 남긴다(본문 그림까지 실으면 양식 책 그림이 통째로 따라온다)
    keep_bin = set()
    for name, data in files.items():
        if name == "Contents/header.xml" or re.match(r"Contents/masterpage\d+\.xml$", name):
            keep_bin |= set(re.findall(r'binaryItemIDRef="([^"]+)"', data.decode("utf-8", "replace") if isinstance(data, bytes) else data))
    # 패키지: content.hpf 에 그림·구역을 적는다(양식의 다른 구역은 뺀다)
    hpf = files["Contents/content.hpf"].decode("utf-8")
    if title:
        hpf = re.sub(r"<opf:title>.*?</opf:title>", f"<opf:title>{_esc(html.unescape(title.group(1).strip()))}</opf:title>", hpf, count=1)
    hpf = re.sub(r'<opf:item id="([^"]+)" href="BinData/[^"]*"[^>]*/>',
                 lambda m: m.group(0) if m.group(1) in keep_bin else "", hpf)
    hpf = re.sub(r'<opf:item id="section[1-9]\d*"[^>]*/>', "", hpf)
    hpf = re.sub(r'<opf:itemref idref="section[1-9]\d*"[^>]*/>', "", hpf)
    items = "".join(f'<opf:item id="{it}" href="BinData/{it}.{ext}" media-type="image/{"jpeg" if ext == "jpg" else ext}" isEmbeded="1"/>'
                    for it, _, ext in w.images)
    hpf = hpf.replace('<opf:item id="section0"', items + '<opf:item id="section0"', 1)
    rdf = files.get("META-INF/container.rdf", b"").decode("utf-8")
    rdf = re.sub(r'<rdf:Description rdf:about="">\s*<ns0:hasPart [^>]*rdf:resource="Contents/section[1-9]\d*.xml"/>\s*</rdf:Description>'
                 r'<rdf:Description rdf:about="Contents/section[1-9]\d*.xml">.*?</rdf:Description>', "", rdf, flags=re.S)
    plain = "\n".join("".join(r.text for r in blk[1]) for blk in b.blocks if blk[0] == "p")[:3000]

    os.makedirs(os.path.dirname(os.path.abspath(out_hwpx)) or ".", exist_ok=True)
    with zipfile.ZipFile(out_hwpx, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(zipfile.ZipInfo("mimetype"), b"application/hwp+zip", compress_type=zipfile.ZIP_STORED)
        for name, data in files.items():
            if name == "mimetype" or re.match(r"Contents/section[1-9]\d*\.xml$", name):
                continue
            if name.startswith("BinData/") and os.path.splitext(os.path.basename(name))[0] not in keep_bin:
                continue
            if name == "Contents/header.xml":
                data = header.encode("utf-8")
            elif name == "Contents/section0.xml":
                data = section.encode("utf-8")
            elif name == "Contents/content.hpf":
                data = hpf.encode("utf-8")
            elif name == "META-INF/container.rdf":
                data = rdf.encode("utf-8")
            elif name == "Preview/PrvText.txt":
                data = plain.encode("utf-8")
            z.writestr(name, data)
        for it, path, ext in w.images:
            with open(path, "rb") as f:
                z.writestr(f"BinData/{it}.{ext}", f.read())
    shutil.rmtree(b.tmp, ignore_errors=True)
    return {"out": out_hwpx, "paragraphs": counts["p"], "tables": counts["tbl"], "images": counts["img"],
            "svg_tool": bool(b.svg_tool)}


def _all(n):
    yield n
    if isinstance(n, Node):
        for k in n.kids:
            yield from _all(k)


def main(argv=None):
    ap = argparse.ArgumentParser(description="HTML → 한글(HWPX) — 표준 라이브러리만")
    ap.add_argument("html")
    ap.add_argument("-o", "--out")
    ap.add_argument("--page", default="188x257", help="쪽 크기 mm (기본 188x257 = 46배판, A4 는 210x297, keep = 양식 그대로)")
    ap.add_argument("--margin", type=float, default=15.0, help="쪽 여백 mm (기본 15)")
    ap.add_argument("--template", help="양식 .hwpx — 글꼴·스타일·쪽 설정을 이것에서 가져온다")
    ap.add_argument("--font", default=None, help="본문 글꼴 (기본: 양식이 있으면 양식 글꼴, 없으면 맑은 고딕)")
    ap.add_argument("--styles", default="", help='양식 스타일 짝 바꾸기 예: "body=*본문,h2=*1.제목,cell=*표내용"')
    ap.add_argument("--head", default=None, help="바탕쪽 머리말 글자 (기본: HTML <title>)")
    a = ap.parse_args(argv)
    page = "keep" if a.page == "keep" else tuple(float(x) for x in a.page.lower().split("x"))
    out = a.out or os.path.splitext(a.html)[0] + ".hwpx"
    styles = dict(x.split("=", 1) for x in a.styles.split(",") if "=" in x)
    font = a.font if a.font is not None else (None if a.template else "맑은 고딕")
    r = convert(a.html, out, page=page, margin_mm=None if (a.template and a.page == "keep") else a.margin,
                template=a.template, font=font or None, styles=styles, head=a.head)
    print(f"→ {r['out']}  (문단 {r['paragraphs']} · 표 {r['tables']} · 그림 {r['images']})")
    if not r["svg_tool"]:
        print("  참고: Edge/Chrome 을 못 찾아 SVG 그림은 옆의 .png 가 있을 때만 들어갑니다")
    return 0


# 한글이 저장한 빈 문서(한컴오피스 한글, 2026-11-03) — 양식을 주지 않으면 이것을 틀로 쓴다
BASE_HWPX = """
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
"""

if __name__ == "__main__":
    sys.exit(main())
