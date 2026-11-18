"""영상 보며 검수 — 완성 강 영상(out/Lxx/Lxx.mp4)의 **몇 초가 몇 장 몇 번째 문장인가.**

★ 왜 있나 — 40분짜리 강을 장마다 열어 들으며 발음을 고치면 검수가 끝나지 않는다. 영상을 보다가
  이상한 곳에서 M 만 누르고, 검수표의 장을 눌러 ④ 음성 체크의 **그 장 발음 칸**으로 간다.
  요약반 앱(261013-backplate_showcase-master-onlycodex `render/review_video.py`·`static/js/review.js`)과
  해설북 스튜디오(⑤ 음성 체크 「영상 보며 검수」)에서 먼저 해 본 방식을 1부 강의에 옮긴 것(2026-11-18).

★ 시간의 출처는 **그 영상을 구운 결과**다 — s4_stitch 와 같은 규칙으로 센다:
  섹션 시작 = 앞 섹션 mp4 실제 길이(ffprobe) 누적, 장 길이 = 오디오 + 0.45초(TAIL_SEC, 없으면 4초),
  장 안 문장 = 엔진이 낸 장별 자막(08_자막/NNN.srt). 음성을 다시 합성해도 이미 구운 영상과 어긋나지 않는다.

★ 다른 PC 에서도 검수한다 — 영상 옆에 서버 없이 열리는 `Lxx-영상검수.html` 을 만들고
  「드라이브로 보내기」가 영상과 함께 `<구글 드라이브>/영상검수/<잡>/` 에 복사한다. 집 노트북에서
  그 html 로 듣고 「검수표 저장」으로 같은 폴더에 `Lxx-검수표.json` 을 두면, 여기 패널이 알려 준다.

검수표 = out/<강>/review_marks.json — {"marks": [{no, key, i, t, text, memo}], "heard": [no…], "drive_seen": {}}
    no   ④ 음성 체크의 장 번호(1부터 — 화면 번호 칩과 같다)
    key  그 장의 발음 키(data_id · <섹션>:cover · <섹션>:outro) — 다시 렌더해 번호가 바뀌어도 장을 찾는다
    i    그 장의 몇 번째 자막 문장(0부터)
    t    영상 시각(초)
"""
from __future__ import annotations

import html
import json
import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from longform.config import Job
from longform.util import ffprobe_duration, read_json, write_json

TAIL_SEC = 0.45                       # longform/s4_stitch.py 와 같아야 한다
F_MARKS = "review_marks.json"
TS_RE = re.compile(r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)")


def _lecture(job: Job, lid: str) -> Dict[str, Any]:
    cur = read_json(job.dir / "curriculum.json", {}) or {}
    L = next((x for x in cur.get("lectures", []) if x["id"] == lid), None)
    if not L:
        raise ValueError(f"강이 없습니다: {lid}")
    return L


def video_path(job: Job, lid: str) -> Path:
    return job.out_dir / lid / f"{lid}.mp4"


def _here(job: Job, p: str) -> Path:
    """timing.json 의 절대 경로가 옛 폴더(예: 261001-longform-full-auto)를 가리키면 이 잡 폴더로 옮겨 읽는다."""
    q = Path(p or "")
    if not p or q.exists():
        return q
    parts = q.parts
    for i in range(len(parts) - 1):
        if parts[i].lower() == "jobs" and parts[i + 1] == job.name:
            return job.dir.joinpath(*parts[i + 2:])
    return q


def _t(h, m, s, ms) -> float:
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms.ljust(3, "0")[:3]) / 1000


def _read_srt(p: Path) -> List[Dict[str, Any]]:
    if not p.is_file():
        return []
    txt = p.read_text(encoding="utf-8-sig", errors="replace").replace("\r\n", "\n")
    out = []
    for block in re.split(r"\n\s*\n", txt.strip()):
        lines = block.strip().split("\n")
        for i, ln in enumerate(lines):
            m = TS_RE.search(ln)
            if m:
                g = m.groups()
                out.append({"a": _t(*g[:4]), "b": _t(*g[4:]), "text": " ".join(lines[i + 1:]).strip()})
                break
    return out


def _durations(job: Job, lid: str, parts: List[Path]) -> List[float]:
    """섹션 mp4 길이 — ffprobe 는 느리지 않지만 패널을 열 때마다 재지 않게 크기·시각으로 캐시."""
    cache_p = job.out_dir / lid / ".review_dur.json"
    cache = read_json(cache_p, {}) or {}
    out, dirty = [], False
    for p in parts:
        st = p.stat()
        sig = f"{st.st_size}:{int(st.st_mtime)}"
        hit = cache.get(p.name) or {}
        if hit.get("sig") != sig:
            hit = {"sig": sig, "sec": ffprobe_duration(p)}
            cache[p.name] = hit
            dirty = True
        out.append(float(hit["sec"]))
    if dirty:
        try:
            write_json(cache_p, cache)
        except OSError:
            pass
    return out


def cues(job: Job, lid: str) -> Dict[str, Any]:
    """영상 시각 → 장·문장 표. 영상이 없으면 video 가 빈다."""
    from longform import voice
    L = _lecture(job, lid)
    mp4 = video_path(job, lid)
    pdir = job.out_dir / lid / "parts"
    parts = [pdir / f"{s['id']}.mp4" for s in L["sections"]]
    if not mp4.is_file() or not all(p.is_file() for p in parts):
        return {"video": "", "cues": [], "rows": 0}
    rows = voice.rows(job, lid)["rows"]
    by_pos = {(r["sid"], int(r["no"])): (i + 1, r) for i, r in enumerate(rows)}
    out: List[Dict[str, Any]] = []
    off = 0.0
    for sec, p, dur_part in zip(L["sections"], parts, _durations(job, lid, parts)):
        tm = read_json(p.with_suffix(".timing.json"), {}) or {}
        t = off
        for s in tm.get("slides") or []:
            au = float(s.get("audio_sec") or 0)
            dur = (au + TAIL_SEC) if au > 0 else 4.0
            hit = by_pos.get((sec["id"], int(s.get("no") or 0)))
            if hit:
                no, r = hit
                title = r.get("title") or s.get("title") or ""
                pieces = _read_srt(_here(job, s.get("srt") or ""))
                if not pieces:
                    out.append({"start": round(t, 2), "end": round(t + dur, 2), "no": no, "key": r["key"],
                                "i": 0, "title": title, "text": (r.get("say") or title)[:120]})
                for i, c in enumerate(pieces):
                    # 마지막 문장은 장 끝(숨 TAIL 포함)까지 — 틈이 생기면 표시가 앞 장으로 간다
                    end = t + (dur if i == len(pieces) - 1 else c["b"])
                    out.append({"start": round(t + c["a"], 2), "end": round(end, 2), "no": no, "key": r["key"],
                                "i": i, "title": title, "text": c["text"]})
            t += dur
        off += dur_part
    return {"video": f"out/{lid}/{mp4.name}", "name": mp4.name, "cues": out, "rows": len(rows),
            "sec": round(off, 2)}


# ── 검수표 ───────────────────────────────────────────────────────────────
def _doc_path(job: Job, lid: str) -> Path:
    return job.out_dir / lid / F_MARKS


def _doc(job: Job, lid: str) -> Dict[str, Any]:
    return read_json(_doc_path(job, lid), {}) or {}


def load_marks(job: Job, lid: str) -> List[Dict[str, Any]]:
    return list(_doc(job, lid).get("marks") or [])


def save_marks(job: Job, lid: str, marks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    clean: List[Dict[str, Any]] = []
    seen: Dict[Any, Dict[str, Any]] = {}
    for m in marks or []:
        try:
            no, i, t = int(m.get("no")), int(m.get("i") or 0), float(m.get("t") or 0)
        except (TypeError, ValueError):
            continue
        memo = str(m.get("memo") or "")[:300]
        k = (str(m.get("key") or no), i)
        if k in seen:                       # 같은 자리를 두 PC 에서 찍었으면 하나로 — 메모는 살린다
            if memo and not seen[k]["memo"]:
                seen[k]["memo"] = memo
            continue
        one = {"no": no, "key": str(m.get("key") or ""), "i": i, "t": round(t, 1),
               "text": str(m.get("text") or "")[:200], "memo": memo}
        seen[k] = one
        clean.append(one)
    clean.sort(key=lambda m: m["t"])
    doc = _doc(job, lid)
    doc.update({"marks": clean, "at": datetime.now().isoformat(timespec="seconds")})
    write_json(_doc_path(job, lid), doc)
    return clean


def load_heard(job: Job, lid: str) -> List[int]:
    return sorted({int(x) for x in _doc(job, lid).get("heard") or []})


def add_heard(job: Job, lid: str, nos: List[int], *, reset: bool = False) -> List[int]:
    doc = _doc(job, lid)
    got = set() if reset else {int(x) for x in doc.get("heard") or []}
    got |= {int(x) for x in nos or []}
    doc["heard"] = sorted(got)
    write_json(_doc_path(job, lid), doc)
    return doc["heard"]


# ── 구글 드라이브 ─────────────────────────────────────────────────────────
def drive_root() -> Optional[Path]:
    """드라이브 데스크톱의 「내 드라이브」 — 환경변수 LONGFORM_DRIVE(또는 SHOWCASE_DRIVE) → G: 순."""
    want = (os.environ.get("LONGFORM_DRIVE") or os.environ.get("SHOWCASE_DRIVE") or "").strip()
    for c in ([want] if want else ["G:/내 드라이브", "G:/My Drive"]):
        p = Path(c)
        if p.is_dir():
            return p
    return None


def drive_dir(job: Job, *, create: bool = False) -> Optional[Path]:
    root = drive_root()
    if root is None:
        return None
    d = root / "영상검수" / job.name
    if create:
        d.mkdir(parents=True, exist_ok=True)
    return d


def to_drive(job: Job, lid: str) -> Dict[str, Any]:
    """검수 html 을 새로 만들고 영상과 함께 드라이브 폴더에 복사(영상은 바뀌었을 때만)."""
    page = export(job, lid)
    if page is None:
        raise ValueError("완성 영상이 아직 없습니다")
    d = drive_dir(job, create=True)
    if d is None:
        raise ValueError("구글 드라이브(G:/내 드라이브)를 찾지 못했습니다 — 드라이브 데스크톱에 로그인하세요")
    mp4 = video_path(job, lid)
    dst = d / mp4.name
    st = mp4.stat()
    copied = False
    if not (dst.is_file() and dst.stat().st_size == st.st_size and dst.stat().st_mtime >= st.st_mtime - 2):
        shutil.copy2(mp4, dst)
        copied = True
    shutil.copy2(page, d / page.name)
    return {"ok": True, "dir": str(d), "video_copied": copied, "mb": round(st.st_size / 1e6, 1), "page": page.name}


def drive_inbox(job: Job, lid: str) -> Dict[str, Any]:
    """드라이브 폴더에 아직 안 가져온 이 강의 검수표(Lxx-검수표*.json)가 있나."""
    d = drive_dir(job)
    if d is None or not d.is_dir():
        return {"dir": str(d) if d else "", "files": []}
    seen = _doc(job, lid).get("drive_seen") or {}
    files = []
    for f in sorted(d.glob(f"{lid}*검수표*.json")):
        mt = round(f.stat().st_mtime, 1)
        if seen.get(f.name) == mt:
            continue
        try:
            got = json.loads(f.read_text(encoding="utf-8"))
            n = len(got if isinstance(got, list) else got.get("marks") or [])
        except (OSError, ValueError):
            continue
        files.append({"name": f.name, "n": n, "mtime": mt, "at": datetime.fromtimestamp(mt).strftime("%m-%d %H:%M")})
    return {"dir": str(d), "files": files}


def drive_import(job: Job, lid: str) -> Dict[str, Any]:
    box = drive_inbox(job, lid)
    d = Path(box["dir"]) if box["dir"] else None
    add: List[Dict[str, Any]] = []
    for f in box["files"]:
        got = json.loads((d / f["name"]).read_text(encoding="utf-8"))
        add += got if isinstance(got, list) else (got.get("marks") or [])
    marks = save_marks(job, lid, load_marks(job, lid) + add)
    doc = _doc(job, lid)
    seen = dict(doc.get("drive_seen") or {})
    seen.update({f["name"]: f["mtime"] for f in box["files"]})
    doc["drive_seen"] = seen
    write_json(_doc_path(job, lid), doc)
    return {"marks": marks, "added": len(add), "files": [f["name"] for f in box["files"]]}


def panel(job: Job, lid: str) -> Dict[str, Any]:
    """검수 패널이 한 번에 받는 것 — 시각표 + 검수표 + 들은 장 + 드라이브 새 검수표"""
    c = cues(job, lid)
    c.update(marks=load_marks(job, lid), heard=load_heard(job, lid), drive=drive_inbox(job, lid))
    return c


# ── 서버 없이 여는 검수 파일 ──────────────────────────────────────────────
def export(job: Job, lid: str) -> Optional[Path]:
    """out/<강>/<강>-영상검수.html — 영상과 같은 폴더에 두고 더블클릭으로 연다."""
    c = cues(job, lid)
    if not c["video"]:
        return None
    mp4 = video_path(job, lid)
    out = mp4.with_name(mp4.stem + "-영상검수.html")
    title = f"{job.get('title') or job.name} · {lid} {_lecture(job, lid).get('title', '')}"
    data = {"video": mp4.name, "title": title, "cues": c["cues"], "marks": load_marks(job, lid),
            "at": datetime.now().strftime("%Y-%m-%d %H:%M")}
    page = (_PAGE.replace("__TITLE__", html.escape(title))
            .replace("__DATA__", json.dumps(data, ensure_ascii=False).replace("</", "<\\/")))
    out.write_text(page, encoding="utf-8")
    return out


_PAGE = r"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__ · 영상 검수</title>
<style>
:root{--bg:#f6f4ef;--card:#fff;--ink:#22201c;--mut:#7a746a;--line:#e3ded4;--acc:#1F4E79;--hl:#fff3c4}
@media (prefers-color-scheme:dark){:root{--bg:#1c1b19;--card:#262421;--ink:#eee9e0;--mut:#a39c90;--line:#3a3732;--acc:#9DC3E6;--hl:#4a3f1c}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 system-ui,"Malgun Gothic",sans-serif}
header{padding:14px 20px;border-bottom:1px solid var(--line);display:flex;gap:12px;align-items:baseline;flex-wrap:wrap}
header h1{font-size:18px;margin:0}header span{color:var(--mut);font-size:13px}
main{display:grid;grid-template-columns:minmax(0,1.6fr) minmax(300px,1fr);gap:16px;padding:16px 20px}
@media (max-width:900px){main{grid-template-columns:1fr}}
video{width:100%;background:#000;border-radius:8px;aspect-ratio:16/9}
.now{margin-top:8px;padding:8px 10px;background:var(--card);border:1px solid var(--line);border-radius:8px;min-height:44px}
.now b{color:var(--acc);margin-right:6px}
.keys{color:var(--mut);font-size:12.5px;margin-top:6px}
kbd{border:1px solid var(--line);border-bottom-width:2px;border-radius:4px;padding:0 5px;font-size:12px;background:var(--card)}
.side{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px;align-self:start}
.bar{display:flex;gap:6px;flex-wrap:wrap;align-items:center;margin-bottom:8px}
.bar h2{font-size:16px;margin:0 auto 0 0}
button{font:inherit;font-size:13px;padding:5px 10px;border-radius:6px;border:1px solid var(--line);background:var(--card);color:var(--ink);cursor:pointer}
button.pri{background:var(--acc);border-color:var(--acc);color:#fff}
ul{list-style:none;margin:0;padding:0;max-height:70vh;overflow:auto}
li{border-top:1px solid var(--line);padding:7px 2px;display:grid;grid-template-columns:auto 1fr auto;gap:4px 8px;align-items:start}
li.flash{animation:f 1.2s}@keyframes f{from{background:var(--hl)}to{background:transparent}}
li a{color:var(--acc);cursor:pointer;font-variant-numeric:tabular-nums;text-decoration:underline}
li .tx{font-size:13.5px}li .tx b{margin-right:4px}
li input{grid-column:2/4;font:inherit;font-size:13px;padding:4px 6px;border:1px solid var(--line);border-radius:5px;background:var(--bg);color:var(--ink)}
li .x{border:0;background:none;color:var(--mut);padding:0 4px}
.empty{color:var(--mut);font-size:13px;padding:8px 0}
.how{color:var(--mut);font-size:12.5px;margin-top:10px;border-top:1px solid var(--line);padding-top:8px}
</style></head><body>
<header><h1>__TITLE__</h1><span id="sub"></span></header>
<main>
<section>
  <video id="v" controls preload="metadata"></video>
  <div class="now" id="now">재생하면 지금 읽는 문장이 여기 뜹니다.</div>
  <div class="keys"><kbd>M</kbd> 여기 표시 · <kbd>←</kbd><kbd>→</kbd> 5초 · <kbd>Space</kbd> 재생·멈춤 · <kbd>R</kbd> 지금 문장 처음부터</div>
</section>
<aside class="side">
  <div class="bar"><h2 id="cnt">검수표 0줄</h2>
    <button id="mark">📌 여기 표시</button>
    <button class="pri" id="save">검수표 저장</button>
    <button id="clear">비우기</button></div>
  <ul id="list"></ul>
  <div class="how">이상하게 들리는 곳에서 <kbd>M</kbd> 을 누르고, 칸에 무엇이 이상한지 적어 두세요.<br>
  다 들었으면 «검수표 저장» — 저장 창에서 <b>이 html 이 있는 드라이브 폴더</b>를 고르세요.
  회사 PC 강의 앱 ④ 음성 체크의 «영상 보며 검수» 에 「드라이브에 새 검수표」로 뜹니다.<br>
  표시는 이 브라우저에도 남으므로 창을 닫았다 열어도 이어서 할 수 있습니다.</div>
</aside>
</main>
<script>
const D = __DATA__;
const LAG = 1.5, KEY = "review:" + D.title + ":" + D.video;
const v = document.getElementById("v"), $ = (id) => document.getElementById(id);
v.src = encodeURI(D.video);
v.onerror = () => { $("now").textContent = "영상을 못 찾았습니다 — 이 파일과 " + D.video + " 를 같은 폴더에 두세요."; };
$("sub").textContent = `${D.cues.length}문장 · ${D.at} 에 만듦`;
let marks = D.marks || [];
try { const s = JSON.parse(localStorage.getItem(KEY) || "null"); if (s && s.length >= marks.length) marks = s; } catch {}
const fmt = (t) => `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, "0")}`;
const at = (t) => { let k = -1; for (let i = 0; i < D.cues.length && D.cues[i].start <= t; i++) k = i; return k < 0 ? 0 : k; };
const keep = () => { try { localStorage.setItem(KEY, JSON.stringify(marks)); } catch {} };
const pos = "pos:" + KEY; let lastSave = 0;
v.addEventListener("loadedmetadata", () => { let t = 0; try { t = Number(localStorage.getItem(pos) || 0); } catch {} if (t > 5) v.currentTime = t; }, {once: true});
function draw(flashKey) {
  $("cnt").textContent = `검수표 ${marks.length}줄`;
  const ul = $("list"); ul.textContent = "";
  if (!marks.length) { ul.innerHTML = '<div class="empty">아직 없습니다.</div>'; return; }
  for (const m of marks) {
    const li = document.createElement("li");
    if (flashKey === m.no + ":" + m.i) li.className = "flash";
    const a = document.createElement("a"); a.textContent = fmt(m.t);
    a.onclick = () => { v.currentTime = Math.max(0, m.t - 2); v.play(); };
    const tx = document.createElement("div"); tx.className = "tx";
    const b = document.createElement("b"); b.textContent = m.no + "장";
    tx.append(b, document.createTextNode(m.text || ""));
    const x = document.createElement("button"); x.className = "x"; x.textContent = "✕"; x.title = "빼기";
    x.onclick = () => { marks = marks.filter((y) => !(y.no === m.no && y.i === m.i)); keep(); draw(); };
    const memo = document.createElement("input"); memo.placeholder = "무엇이 이상한가 (예: 니은 디귿으로 읽어야)";
    memo.value = m.memo || ""; memo.oninput = () => { m.memo = memo.value; keep(); };
    li.append(a, tx, x, memo); ul.appendChild(li);
  }
}
function mark() {
  if (!D.cues.length) return;
  const c = D.cues[at(Math.max(0, v.currentTime - LAG))];
  const k = c.no + ":" + c.i;
  if (!marks.some((m) => m.no + ":" + m.i === k)) {
    marks.push({no: c.no, key: c.key, i: c.i, t: Math.round(v.currentTime * 10) / 10, text: c.text, memo: ""});
    marks.sort((a, b) => a.t - b.t); keep();
  }
  draw(k);
}
function now() {
  if (!D.cues.length) return;
  const c = D.cues[at(v.currentTime)];
  $("now").innerHTML = ""; const b = document.createElement("b"); b.textContent = c.no + "장";
  $("now").append(b, document.createTextNode(c.text));
  if (Math.abs(v.currentTime - lastSave) > 2) { lastSave = v.currentTime; try { localStorage.setItem(pos, String(Math.floor(v.currentTime))); } catch {} }
}
v.addEventListener("timeupdate", now); v.addEventListener("seeked", now);
$("mark").onclick = (e) => { e.currentTarget.blur(); mark(); };
$("clear").onclick = (e) => { e.currentTarget.blur(); if (marks.length && confirm("검수표를 비울까요?")) { marks = []; keep(); draw(); } };
$("save").onclick = async (e) => {
  e.currentTarget.blur();
  const name = D.video.replace(/\.mp4$/i, "") + "-검수표.json";
  const text = JSON.stringify({video: D.video, saved: new Date().toISOString(), marks}, null, 1);
  if (window.showSaveFilePicker) {
    try {
      const h = await showSaveFilePicker({id: "review", suggestedName: name,
        types: [{description: "검수표", accept: {"application/json": [".json"]}}]});
      const w = await h.createWritable(); await w.write(text); await w.close();
      $("now").textContent = `저장했습니다 — ${h.name} (${marks.length}줄). 회사 PC 검수 패널에 뜹니다.`;
      return;
    } catch (err) { if (err && err.name === "AbortError") return; }
  }
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text], {type: "application/json"}));
  a.download = name; a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  $("now").textContent = "내려받았습니다 — 받은 파일을 이 html 이 있는 드라이브 폴더로 옮기세요.";
};
addEventListener("keydown", (e) => {
  const t = e.target; if (e.ctrlKey || e.altKey || e.metaKey) return;
  if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA")) return;
  const k = e.code;
  if (k === "KeyM") mark();
  else if (k === "ArrowLeft") v.currentTime = Math.max(0, v.currentTime - 5);
  else if (k === "ArrowRight") v.currentTime += 5;
  else if (k === "Space") v.paused ? v.play() : v.pause();
  else if (k === "KeyR" && D.cues.length) { v.currentTime = D.cues[at(v.currentTime)].start; v.play(); }
  else return;
  e.preventDefault(); e.stopPropagation();
}, true);
draw();
</script></body></html>
"""
