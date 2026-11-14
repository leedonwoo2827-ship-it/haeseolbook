"""음성 체크 — 렌더된 강을 장마다 **귀로 듣고** 발음(TTS 입력)을 고친다.

    고친 발음   jobs/<잡>/voice/<Lxx>.json   {키: {"read": "...", "checked": true}}
                키 = 장의 data_id(L01-s1-01-003) · 표지 = "<섹션>:cover" · 맺음 = "<섹션>:outro"
    발음 사전   jobs/<잡>/voice/dict.json    [{"from": "CPU", "to": "씨피유"}, …] — 모든 강의 발음에 적용

흐름  화면에서 고침 → 「발음대로 다시 합성」(그 장만, 엔진 s10_tts.synth_one — 바로 다시 들어 봄)
      → 「음성 고친 판 굽기」(make --only Lxx). 렌더(s3)는 effective_read 를 덮어쓰기 narration 에 싣고,
        고친 것이 있는 섹션만 해시가 바뀌어 다시 굽는다(고친 것이 없으면 해시·화면 그대로).
★ 자막(say)은 바꾸지 않는다 — 화면에 보이는 원문은 원고(manuscripts/)가 원본이다.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from longform.config import Job
from longform.state import State, sha
from longform.util import read_json, write_json


def _dir(job: Job):
    return job.dir / "voice"


def load_overlay(job: Job, lid: str) -> Dict[str, Dict[str, Any]]:
    return read_json(_dir(job) / f"{lid}.json", {}) or {}


def save_overlay(job: Job, lid: str, key: str, read: Optional[str] = None, checked: Optional[bool] = None) -> None:
    ov = load_overlay(job, lid)
    one = ov.setdefault(key, {})
    if read is not None:
        one["read"] = read
    if checked is not None:
        one["checked"] = bool(checked)
    write_json(_dir(job) / f"{lid}.json", ov)


DEFAULT_DICT = Path(__file__).with_name("voice_dict.json")   # 레포 기본 사전 — 모든 잡에 깔린다(SRAM→에스램 …)


def load_dict(job: Job) -> List[Dict[str, str]]:
    """기본 사전(longform/voice_dict.json) 위에 잡 사전(jobs/<잡>/voice/dict.json). 같은 「from」은 잡 사전이 이긴다."""
    merged: Dict[str, Dict[str, str]] = {}
    for src in (read_json(DEFAULT_DICT, []) or [], read_json(_dir(job) / "dict.json", []) or []):
        for d in src:
            f = (d.get("from") or "").strip()
            if f:
                merged[f] = {"from": f, "to": (d.get("to") or "").strip()}
    return list(merged.values())


def save_dict(job: Job, rows: List[Dict[str, str]]) -> None:
    rows = [{"from": r["from"].strip(), "to": (r.get("to") or "").strip()} for r in rows if (r.get("from") or "").strip()]
    write_json(_dir(job) / "dict.json", rows)


def apply_dict(text: str, rows: List[Dict[str, str]]) -> str:
    # 긴 말부터 바꾼다(「SQL」보다 「MySQL」이 먼저). 영문은 낱말 경계로만 — 「CPU」가 「CPUs」 안을 깨지 않게
    for r in sorted(rows, key=lambda r: -len(r["from"])):
        f = r["from"]
        if re.fullmatch(r"[A-Za-z0-9_.+-]+", f):
            text = re.sub(rf"(?<![A-Za-z0-9]){re.escape(f)}(?![A-Za-z0-9])", r["to"], text)
        else:
            text = text.replace(f, r["to"])
    return text


def effective_read(job: Job, lid: str, key: str, say: str, read: str,
                   ov: Optional[Dict[str, Any]] = None, rows: Optional[List[Dict[str, str]]] = None) -> str:
    """실제로 TTS 에 넣을 글 — 손으로 고친 것(있으면) 위에 발음 사전."""
    ov = load_overlay(job, lid) if ov is None else ov
    rows = load_dict(job) if rows is None else rows
    from longform.s2_manuscript import fix_counters
    mine = (ov.get(key) or {}).get("read")
    if mine is not None and mine.strip():
        base = mine                                     # 손으로 고친 것은 그대로
    else:
        base = fix_counters(read or say or "")          # 원고 발음도 숫자+단위(「01회」→「일 회」)는 한 번 더 바로잡는다
    return apply_dict(base, rows) if rows else base


def render_read(job: Job, lid: str, key: str, say: str, read: str,
                ov: Optional[Dict[str, Any]] = None, rows: Optional[List[Dict[str, str]]] = None) -> str:
    """렌더가 덮어쓰기에 싣는 발음 — 고친 것이 없으면 **원고 그대로**(빈 발음은 비워 둬 엔진이 자막에서 만든다)."""
    r1 = effective_read(job, lid, key, say, read, ov, rows)
    return r1 if r1 != (read or say) else read


def section_sig(job: Job, lid: str, man: Dict[str, Any], sid: str) -> Optional[str]:
    """이 섹션의 발음이 원고와 달라졌으면 그 해시(렌더 해시에 넣는다), 같으면 None — 화면·해시 그대로."""
    ov, rows = load_overlay(job, lid), load_dict(job)
    if not ov and not rows:
        return None
    diff = []
    items = [(f"{sid}:cover", man.get("cover") or {}), (f"{sid}:outro", man.get("outro") or {})]
    items += [(s["id"], s) for g in man.get("groups", []) for s in g.get("slides", [])]
    for key, s in items:
        if not s.get("say"):
            continue
        r0 = s.get("read", "") or ""
        r1 = effective_read(job, lid, key, s["say"], r0, ov, rows)
        if r1 != (r0 or s["say"]):
            diff.append((key, r1))
    return sha(*[f"{k}={v}" for k, v in diff]) if diff else None


def rows(job: Job, lid: str) -> Dict[str, Any]:
    """강 하나의 장 목록 — 렌더된 섹션(parts/<섹션>.timing.json)만. 장 순서는 영상 순서."""
    cur = read_json(job.dir / "curriculum.json", {}) or {}
    L = next((x for x in cur.get("lectures", []) if x["id"] == lid), None)
    if not L:
        raise ValueError(f"강이 없습니다: {lid}")
    ov, dic = load_overlay(job, lid), load_dict(job)
    state = State(job)
    out: List[Dict[str, Any]] = []
    for si, sm in enumerate(L["sections"]):
        sid = sm["id"]
        man = read_json(job.manuscripts_dir / lid / f"{sid}.json", {}) or {}
        tm = read_json(job.out_dir / lid / "parts" / f"{sid}.timing.json", {}) or {}
        pid = (state.get(lid, f"s3:{sid}") or {}).get("pid")
        by_id = {s["id"]: s for g in man.get("groups", []) for s in g.get("slides", [])}
        tl = tm.get("slides") or []
        for i, t in enumerate(tl):
            did = t.get("data_id") or ""
            if did:
                key, src = did, by_id.get(did) or {}
            elif i == 0 and si == 0:
                key, src = f"{sid}:cover", man.get("cover") or {}
            elif i == len(tl) - 1 and si == len(L["sections"]) - 1:
                key, src = f"{sid}:outro", man.get("outro") or {}
            else:
                continue
            say = src.get("say") or ""
            if not say:
                continue
            mine = ov.get(key) or {}
            out.append({"key": key, "sid": sid, "no": t["no"], "pid": pid, "title": t.get("title") or "",
                        "say": say, "read_orig": src.get("read") or "",
                        "read": effective_read(job, lid, key, say, src.get("read") or "", ov, dic),
                        "edited": bool((mine.get("read") or "").strip()), "checked": bool(mine.get("checked")),
                        "sec": t.get("audio_sec") or 0, "project": tm.get("project") or ""})
    return {"lecture": lid, "title": L["title"], "rows": out,
            "checked": sum(1 for r in out if r["checked"]), "total": len(out)}


AI_PROMPT = """너는 한국어 TTS(음성 합성) 발음 교정기다. 아래 [자막]을 TTS 가 **소리 나는 대로** 읽을 글로 바꿔라.
규칙:
- 영문 약어·용어는 한국어 발음으로(CPU→씨피유, SSD→에스에스디, Excel→엑셀, VLOOKUP→브이룩업, SUM→썸).
- 숫자·기호는 문맥에 맞게 읽는 대로(2급→이 급, 1과목→일 과목, 3개→세 개, 50%→오십 퍼센트, A1→에이 일, =→이퀄).
- 회차·번호의 앞자리 0 은 읽지 않는다(01회→일 회, 03번→삼 번 — 「공일」「영삼」으로 읽지 마라).
- 숫자 앞의 음수 부호는 소리 내어 읽는다(-20→마이너스 이십, -1→마이너스 일). 뺄셈 3-2 는 삼 빼기 이.
- 비트열은 한 자리씩 영·일로(00010100→영 영 영 일 영 일 영 영 — 「공」이 아니라 「영」). 8비트→팔비트, 16진수→십육진수, 20을→이십을.
- 십육진수 값은 한 자씩(EC→이 씨, 2D→이 디, E→이, C→씨, F→에프).
- 함수식·셀 주소는 강사가 말하듯 풀어 읽는다($A$1→달러 에이 달러 일).
- 그 밖의 글자·어순·문장부호는 바꾸지 마라. 설명·따옴표 없이 바꾼 글 한 덩어리만 출력하라.
{hint}
[자막]
{say}"""


# ── 첫 녹음 전 자동 AI 발음 교정 ─────────────────────────────────────────────
# ★ 사용자 지시(2026-11-04): 규칙(fix_counters)·발음 사전을 거치고도 영문·숫자·기호가 남는 줄은
#   **첫 녹음(렌더) 전에** AI 발음 교정을 돌려 원고의 read 에 넣어 둔다 — 음성 체크에서 하나씩 고치지 않게.
#   섹션마다 Claude 1회(남은 줄만 묶어서). 한 번 교정한 줄은 「read_ai」 표시로 다시 부르지 않는다.
#   끄기: 목표서 voice.auto_ai = false
LEFT_RE = re.compile(r"[A-Za-z0-9+=%$#&*/<>^~|⊞@\\]")

AI_BATCH_PROMPT = """너는 한국어 TTS(음성 합성) 발음 교정기다. 아래 JSON 의 각 항목(자막)을 TTS 가 **소리 나는 대로** 읽을 글로 바꿔라.
규칙:
- 영문 약어·용어는 한국어 발음으로(CPU→씨피유, Bluetooth→블루투스, Windows 11→윈도우즈 십일, VLOOKUP→브이룩업, SELECT→셀렉트).
- 숫자·기호는 문맥에 맞게 읽는 대로(2급→이 급, 1과목→일 과목, 3개→세 개, 50%→오십 퍼센트, A1→에이 일, =→이퀄, -20→마이너스 이십).
- 회차·번호의 앞자리 0 은 읽지 않는다(01회→일 회). 비트열은 한 자리씩 영·일(0101→영 일 영 일), 십육진수는 한 자씩(EC→이 씨).
- 키 조합: ⊞+A→윈도우 단축키와 A, Ctrl+C→컨트롤 씨.
- 그 밖의 글자·어순·문장부호는 바꾸지 마라. 결과에 영문·아라비아 숫자·기호가 남지 않게 하라.
- 출력은 같은 키의 JSON 객체 하나만(설명·코드펜스 없이): {{"1": "...", "2": "..."}}
{items}"""


def leftover(job: Job, text: str, rows: Optional[List[Dict[str, str]]] = None) -> bool:
    """규칙·사전을 거친 뒤에도 영문·숫자·기호가 남는가(화면의 「영문·숫자·기호 남음」과 같은 기준)."""
    from longform.s2_manuscript import fix_counters
    rows = load_dict(job) if rows is None else rows
    return bool(LEFT_RE.search(apply_dict(fix_counters(text or ""), rows)))


def auto_ai_fix(job: Job, slides: List[Dict[str, Any]]) -> int:
    """slides = [{"say","read",…}] — 남은 줄만 묶어 AI 교정 후 read 를 고쳐 넣는다(제자리 수정). 고친 줄 수."""
    if not job.get("voice.auto_ai", True):
        return 0
    from longform.s2_manuscript import call_llm, fix_counters, parse_json
    from longform.util import warn
    rows = load_dict(job)
    todo = [s for s in slides if (s.get("say") or "").strip() and not s.get("read_ai")
            and leftover(job, s.get("read") or s["say"], rows)]
    if not todo:
        return 0
    items = {str(i + 1): apply_dict(fix_counters(s.get("read") or s["say"]), rows) for i, s in enumerate(todo)}
    import json
    try:
        out = parse_json(call_llm(job, AI_BATCH_PROMPT.format(items=json.dumps(items, ensure_ascii=False, indent=1))))
    except Exception as e:                      # 교정 실패는 녹음을 막지 않는다 — 규칙·사전 결과로 간다
        warn(f"자동 AI 발음 교정 실패(규칙·사전 발음으로 진행): {e}")
        return 0
    n = 0
    for i, s in enumerate(todo):
        r = (out.get(str(i + 1)) or "").strip().strip("`\"' \n")
        if r:
            s["read"] = fix_counters(r)
            s["read_ai"] = True
            n += 1
    return n


def ai_read(job: Job, say: str, current: str = "") -> str:
    from longform.s2_manuscript import call_llm
    hint = f"(지금 발음 칸: {current} — 이상한 곳만 고쳐라)" if current.strip() else ""
    from longform.s2_manuscript import fix_counters
    out = call_llm(job, AI_PROMPT.format(say=say, hint=hint)).strip()
    return fix_counters(out.strip("`\"' \n"))
