"""음성 체크 — 문장마다 실제로 읽는 소리(발음)를 보고 고쳐 다시 합성한다(생산 허브 「음성 체크」를 옮겨 옴).

  script/voice_fix.json    {줄ID: {tts, src}}   손으로 고친 발음 (src = 고칠 때의 say, 다르면 무효)
  script/voice_check.json  {줄ID: 확인한 tts}   발음이 바뀌면 확인이 풀린다
  state.json voice_ok      「음성 체크 완료 표시」
발음 사전: 공통 studio/pronunciation.yaml · 과목 studio/dict/<과목id>.yaml (같은 키는 과목이 이긴다)
고친 발음·사전은 「음성 고친 판 굽기」(s3→s5)에서 반영된다. 화면에서 미리 합성한 wav 는 s3 가 그대로 쓴다.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from typing import Any, Dict, List, Optional

import yaml

from . import claude
from .job import Job, read_json, write_json
from .tts import engine
from .voice import fixed_tts, fixes, flatten, line_wav

SCOPES = {"공통": lambda subject: engine.PROJECT_PMAP, "과목": engine.subject_dict}
WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]*")
# 수식·기호 — 그대로 두면 TTS 가 건너뛰거나 엉뚱하게 읽는다
MATH_RE = re.compile(r"\w+\^\w+|[A-Za-z]\w*\s*\([^()]{0,12}\)|\d+\s*[/×÷*]\s*\d+|[²³√∑Σ∏≤≥≠≈×÷±∞π∫∂∆∈∉⊂⊃∪∩¬∧∨⊕→←↔₀-₉⁰-⁹^%!]")

AI_PROMPT = """아래는 시험 해설 영상 내레이션(한국어 TTS)의 발음대본이야. TTS 는 한글만 제대로 읽는다.
틀린 부분을 수정해서 각 줄의 전문을 알려줘.
- 영문 · 약어 · 코드 이름은 실제로 읽는 소리를 한글로 (사전에 정해진 건 따르고, 단어는 단어로: super → 슈퍼, this → 디스, static → 스태틱, CPU → 씨피유). 밑줄(_)은 읽지 않는다.
- 숫자는 한국어로 자연스럽게 (2024년 → 이천이십사 년, 제3정규형 → 제삼 정규형, 3개 → 세 개, 0.5 → 영 점 오).
- 수식은 말로 읽는 순서대로: 2^n → 이의 엔 제곱, x² → 엑스 제곱, 2^(n-1) → 이의 엔 마이너스 일 제곱, log₂n → 로그 이 엔, n! → 엔 팩토리얼, a/b → 비 분의 에이, √n → 루트 엔, O(n log n) → 빅오 엔 로그 엔, a mod b → 에이 모드 비, a % b → 에이 나머지 비(퍼센트일 땐 퍼센트).
- 기호: = → 는(같다), ≤ → 이하, ≥ → 이상, ≠ → 같지 않다, < > → 보다 작다·크다, + − × ÷ → 더하기 빼기 곱하기 나누기, ++ → 플러스 플러스, == → 같다, && → 앤드, || → 오어.
- 키 조합의 + 는 더하기로 읽지 않는다: ⊞+D → 윈도우 키와 디, ⊞+Shift+S → 윈도우 키와 시프트 에스, Ctrl+C → 컨트롤 씨 (「윈도우 단축키」라고 하지 않는다).
- 코드 호출은 괄호까지: super() → 슈퍼 괄호, this(x) → 디스 괄호 엑스, print("A") → 프린트 에이.
- 영문·숫자 뒤에 띄어 쓴 조사는 앞말에 붙인다: ROLLBACK 이 → 롤백이, NULL 을 → 널을, SUM(수량) 이 → 썸 괄호 수량이, 20 과 30 → 이십과 삼십. 조사가 아닌 말(ROLLBACK 자체를)은 띄운 그대로.
- 영문+숫자 이름은 붙여 읽는다: A1 → 에이일, S1 → 에스일, M3 → 엠삼. 단 소리가 겹치는 E2 는 이투(「이이」 금지).
- 건 앞 숫자는 고유어 + 된소리로: 3건 → 세 껀, 5건 → 다섯 껀. 개·명·가지 앞도 고유어(두 개, 다섯 명).
- [발음] 이 이미 한글로 맞게 읽히면 바꾸지 않는다(사람이 고친 표기를 되돌리지 않는다).
- 문장 뜻 · 어순 · 조사는 바꾸지 않는다. 고칠 게 없으면 그대로 둔다.
- 참고로 [대본] 은 원래 문장, [자막] 은 화면에 보이는 글이다(고치지 않는다).
- 고친 발음에는 로마자(A~Z, a~z), 아라비아 숫자, 수식 기호가 하나도 남으면 안 된다 — 꼭 한글로 바꾼다.
답은 JSON 객체 하나만: {"줄ID": "고친 발음 전문", ...} — 설명 · 코드펜스 없이.

"""
LEFTOVER = re.compile(r"[A-Za-z0-9²³√∑Σ≤≥≠×÷±∞π^%=<>+*/]")


def _norm(t: str) -> str:
    return re.sub(r"\s+", " ", t or "").strip()


def _ctx(job: Job) -> Dict[str, Any]:
    script = job.script()
    if not script:
        raise ValueError("대본이 없습니다 — 1 대본을 먼저 만드세요")
    return {"script": script, "items": flatten(script), "fx": fixes(job), "subject": job.setting("subject"),
            "voice": job.setting("voice", "F1"), "speed": float(job.setting("speed", 1.0))}


def _item(c: Dict[str, Any], lid: str) -> Dict[str, Any]:
    it = next((x for x in c["items"] if x["id"] == lid), None)
    if not it:
        raise KeyError(f"줄이 없습니다: {lid}")
    return it


def _tts(c: Dict[str, Any], it: Dict[str, Any]) -> str:
    return fixed_tts(c["fx"], it) or engine.spoken(it["say"], c["subject"])


def lines(job: Job) -> Dict[str, Any]:
    c = _ctx(job)
    checks = read_json(job.scripts / "voice_check.json", {}) or {}
    cap_edits = read_json(job.scripts / "cap_edit.json", {}) or {}
    chapters: List[Dict[str, Any]] = []
    for ci, ch in enumerate(c["script"]["chapters"], start=1):
        chapters.append({"i": ci, "title": ch["title"], "quiz": ch.get("quiz"), "kind": ch.get("kind"), "lines": []})
    for it in c["items"]:
        auto = engine.spoken(it["say"], c["subject"])
        mine = fixed_tts(c["fx"], it)
        tts = mine or auto
        chapters[it["chapter"] - 1]["lines"].append({
            "id": it["id"], "say": it["say"], "cap": it["cap"], "tts": tts, "auto": auto,
            "edited": bool(mine), "stale": bool(c["fx"].get(it["id"])) and not mine,
            "ok": checks.get(it["id"]) == tts, "wav": line_wav(job, tts, c["voice"], c["speed"]).exists(),
            "left": bool(LEFTOVER.search(tts)),
            "capEdited": bool(cap_edits.get(it["id"])) and cap_edits[it["id"]].get("orig") != it["cap"],
        })
    total = len(c["items"])
    return {"chapters": [x for x in chapters if x["lines"]], "total": total,
            "checked": sum(1 for x in chapters for ln in x["lines"] if ln["ok"]),
            "voiceOk": bool(job.state().get("voice_ok")), "subject": c["subject"]}


def save_line(job: Job, lid: str, tts: str, synth: bool = False) -> Dict[str, Any]:
    """발음 저장(사전 결과와 같으면 고친 것을 지운다) + 원하면 바로 합성"""
    c = _ctx(job)
    it = _item(c, lid)
    tts = _norm(tts)
    auto = engine.spoken(it["say"], c["subject"])
    if not tts or tts == auto:
        c["fx"].pop(lid, None)
        tts = auto
    else:
        c["fx"][lid] = {"tts": tts, "src": it["say"]}
    write_json(job.scripts / "voice_fix.json", c["fx"])
    wav = line_wav(job, tts, c["voice"], c["speed"])
    if synth and not wav.exists():
        eng = engine.Engine.get()
        engine.write_wav(wav, eng.synth(tts, voice=c["voice"], speed=c["speed"], raw=True), eng.sample_rate)
    return {"ok": True, "tts": tts, "edited": tts != auto, "wav": wav.exists()}


def save_cap(job: Job, lid: str, cap: str) -> Dict[str, Any]:
    """자막(화면 글)만 고친다 — 조사·동격 덧붙이기 같은 작은 손질. 발음·합성은 그대로.
    지금 쓰는 대본(script.edit.json 또는 script.json)에 넣고, 문항 줄이면 script/qNN.json 에도 넣어
    ③ 회차 보기에서 저장(대본 재조립)해도 지워지지 않게 한다. 영상에는 「음성 고친 판 굽기」(s3→s5)에서 반영."""
    cap = "\n".join(_norm(x) for x in (cap or "").splitlines() if x.strip())
    edit = job.dir / "script.edit.json"
    path = edit if read_json(edit) else job.dir / "script.json"
    script = read_json(path)
    if not script:
        raise ValueError("대본이 없습니다 — 1 대본을 먼저 만드세요")
    n = 0
    for ch in script["chapters"]:
        for sc in ch["scenes"]:
            for i, ln in enumerate(sc["lines"]):
                n += 1
                if f"L{n:03d}" != lid:
                    continue
                # 손으로 고친 자막 표시용 — 처음 자막(orig)을 기억, 원래대로 돌리면 지운다
                ce_path = job.scripts / "cap_edit.json"
                ce = read_json(ce_path, {}) or {}
                orig = (ce.get(lid) or {}).get("orig", (ln.get("cap") or ln.get("say") or "").strip())
                if cap == orig or not cap:
                    ce.pop(lid, None)
                else:
                    ce[lid] = {"orig": orig}
                write_json(ce_path, ce)
                ln["cap"] = cap
                write_json(path, script)
                if ch.get("quiz") and sc.get("part"):
                    qp = job.scripts / f"q{int(ch['quiz']):02d}.json"
                    q = read_json(qp)
                    if q and i < len(q.get(sc["part"]) or []):
                        q[sc["part"]][i]["cap"] = cap
                        write_json(qp, q)
                return {"ok": True, "cap": cap or (ln.get("say") or "").strip(), "capEdited": lid in ce}
    raise KeyError(f"줄이 없습니다: {lid}")


def wav_of(job: Job, lid: str):
    c = _ctx(job)
    return line_wav(job, _tts(c, _item(c, lid)), c["voice"], c["speed"])


def check(job: Job, lid: str, tts: str, ok: bool) -> Dict[str, Any]:
    path = job.scripts / "voice_check.json"
    checks = read_json(path, {}) or {}
    if ok:
        checks[lid] = _norm(tts)
    else:
        checks.pop(lid, None)
    write_json(path, checks)
    return {"ok": True}


def ai_fix(job: Job, ids: List[str], current: Dict[str, str], wait: bool = False) -> Dict[str, str]:
    """Claude 에게 발음 교정을 묻는다(저장하지 않음 — 화면에서 보고 적용). 영문·숫자·기호가 남은 줄은 한 번 더."""
    c = _ctx(job)
    items = [_item(c, i) for i in ids]
    body = "".join(f"{it['id']}\n[대본] {it['say']}\n[자막] {it['cap']}\n[발음] {_norm(current.get(it['id']) or _tts(c, it))}\n\n"
                   for it in items)

    def stop(wake):
        if wake and not wait:                      # 화면(버튼)은 바로 알리고, 생산(s3·vfix)은 한도가 풀릴 때까지 기다린다
            raise claude.ClaudeError("Claude 사용 한도에 걸렸습니다 — 나중에 다시 눌러 주세요")

    out: Dict[str, str] = {}
    extra = ""
    for _ in range(2):
        text = claude.ask(AI_PROMPT + body + extra, model=job.setting("voice_ai_model", "sonnet"), cwd=job.dir,
                          on_wait=stop, timeout=240)
        try:
            got = {str(k): _norm(str(v)) for k, v in claude.extract_json(text).items()}
        except (json.JSONDecodeError, AttributeError):
            got = {}
        if len(ids) == 1 and len(got) == 1 and ids[0] not in got:
            got = {ids[0]: next(iter(got.values()))}
        out.update({k: v for k, v in got.items() if k in ids and v})
        bad = [i for i in ids if i not in out or LEFTOVER.search(out[i])]
        if not bad:
            break
        extra = f"\n(앞 답에 로마자 · 숫자 · 기호가 남았거나 빠진 줄이 있었다: {', '.join(bad)} — 다시 전부 한글로.)\n"
    return out


def ai_fix_all(job: Job, workers: int = 4, redo: bool = False) -> int:
    """s3 앞에서 모든 줄을 장마다 AI 발음 교정 → voice_fix.json 에 저장(「이 장 전부 AI 교정」을 생산에 넣은 것).

    손으로 고친 줄은 건드리지 않는다. 한 번 교정한 줄은 script/voice_ai.json {줄ID: say} 로 기억해
    대본이 바뀌지 않으면 다시 묻지 않는다. 고친 줄 수를 돌려준다. 켜기: job.json·시리즈 "voice_ai": true
    redo=True(음성 체크 「한 번에 고치고 굽기」): 「확인」을 누른 줄·손으로 고친 줄만 빼고 전부 지금 규칙으로 다시 묻는다.
    """
    from concurrent.futures import ThreadPoolExecutor
    from .log import log
    c = _ctx(job)
    done_path = job.scripts / "voice_ai.json"
    done = read_json(done_path, {}) or {}
    fx = c["fx"]
    checks = read_json(job.scripts / "voice_check.json", {}) or {}
    todo: Dict[int, List[str]] = {}
    for it in c["items"]:
        f = fx.get(it["id"]) or {}
        hand = f.get("tts") and f.get("src") == it["say"] and f.get("by") != "ai"
        if hand or (not redo and done.get(it["id"]) == it["say"]):
            continue
        if redo and checks.get(it["id"]) == _tts(c, it):        # 사람이 듣고 「확인」한 줄은 그대로
            continue
        todo.setdefault(it["chapter"], []).append(it["id"])
    if not todo:
        log("s3 AI 발음 교정: 새로 볼 줄 없음")
        return 0
    log(f"s3 AI 발음 교정: {sum(len(v) for v in todo.values())}줄 ({len(todo)}장)")

    def ask(ids: List[str]) -> Dict[str, str]:
        try:
            # 다시 물을 때는 지금 규칙의 자동 발음을 바탕으로(예전 AI 답을 그대로 베끼지 않게)
            cur = {i: engine.spoken(_item(c, i)["say"], c["subject"]) for i in ids} if redo else {}
            return ai_fix(job, ids, cur, wait=True)
        except claude.ClaudeError:
            raise                                  # 한도 — s3 를 멈춘다
        except Exception as e:                     # 한 장이 실패해도 다른 장은 살리고, 그 장은 다음 판에 다시
            log(f"  · AI 교정 한 장 실패: {str(e)[:120]}")
            return {}

    got: Dict[str, str] = {}
    for attempt in range(2):                       # 답이 빠졌거나 영문·숫자가 남은 줄만 한 번 더
        with ThreadPoolExecutor(workers) as pool:
            for r in pool.map(ask, [ids for ids in todo.values() if ids]):
                got.update({k: v for k, v in r.items() if v and not LEFTOVER.search(v)})
        todo = {ch: [i for i in ids if i not in got] for ch, ids in todo.items()}
        if not any(todo.values()):
            break
    fx = fixes(job)            # 교정하는 동안 화면에서 손으로 고친 것이 있으면 그것을 살린다
    n = 0
    for lid, tts in got.items():
        it = _item(c, lid)
        f = fx.get(lid) or {}
        if f.get("tts") and f.get("src") == it["say"] and f.get("by") != "ai":
            continue
        tts = _norm(tts)
        if tts != engine.spoken(it["say"], c["subject"]):
            fx[lid] = {"tts": tts, "src": it["say"], "by": "ai"}
            n += 1
        elif f.get("by") == "ai":
            fx.pop(lid, None)
        done[lid] = it["say"]                      # 답을 제대로 받은 줄만 「끝」 — 못 받은 줄은 다음 s3 에서 다시
    write_json(job.scripts / "voice_fix.json", fx)
    write_json(done_path, done)
    left = sum(len(v) for v in todo.values())
    log(f"s3 AI 발음 교정: {n}줄 고침" + (f" · 답을 못 받은 {left}줄은 자동 발음 그대로(다음 s3 에서 다시 묻습니다)" if left else ""))
    return n


# ── 발음 사전 ────────────────────────────────────────────────────────────────
def _rules(path) -> Dict[str, str]:
    if not path or not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {str(k): str(v) for k, v in (data.get("rules") or {}).items()}


def dict_list(subject: Optional[str], job: Optional[Job] = None) -> Dict[str, Any]:
    layers = [("기본", engine.PMAP), ("공통", engine.PROJECT_PMAP), ("과목", engine.subject_dict(subject))]
    merged: Dict[str, Dict[str, Any]] = {}
    for src, path in layers:
        for k, v in _rules(path).items():
            merged[k] = {"k": k, "v": v, "src": src, "over": k in merged}
    out: Dict[str, Any] = {"rules": sorted(merged.values(), key=lambda r: r["k"].lower()),
                           "files": {src: p.relative_to(engine.PROJECT_PMAP.parent.parent).as_posix() if p else "" for src, p in layers}}
    script = job.script() if job else None
    if script:
        # 사전·약어 철자를 거친 뒤에도 남는 영문·수식만 — 손으로 고친 줄은 뺀다
        cnt: Counter = Counter()
        fx = fixes(job)
        for it in flatten(script):
            if fixed_tts(fx, it):
                continue
            said = engine.spoken(it["say"], subject)
            for w in MATH_RE.findall(said) or []:
                cnt[w.strip()] += 1
            for w in WORD_RE.findall(MATH_RE.sub(" ", said)):
                cnt[w] += 1
        out["missing"] = [(w, n) for w, n in cnt.most_common(40) if w]
    return out


def dict_put(subject: Optional[str], k: str, v: str, scope: str = "과목", delete: bool = False) -> Dict[str, Any]:
    """사전 한 줄 넣기·고치기·지우기 — 그 키의 줄만 바꾸고 주석은 그대로 둔다"""
    k, v = k.strip(), _norm(v)
    if scope not in SCOPES or not k or (not delete and not v):
        raise ValueError("표기·소리·범위를 확인하세요")
    path = SCOPES[scope](subject)
    if path is None:
        raise ValueError("과목을 모릅니다")
    old = path.read_text(encoding="utf-8") if path.exists() else (
        f"# {subject} 과목 발음 사전 — 공통 사전(studio/pronunciation.yaml)보다 이긴다. 표기: 소리 (합성 직전에만 바뀌고 자막은 그대로)\nrules:\n")
    pat = re.compile(r"^\s+[\"']?" + re.escape(k) + r"[\"']?\s*:.*\n?", re.M)
    text = pat.sub("", old)
    if not delete:
        text = text.rstrip("\n") + "\n" + f"  {json.dumps(k, ensure_ascii=False)}: {json.dumps(v, ensure_ascii=False)}\n"
    try:
        data = yaml.safe_load(text) or {}
        assert isinstance(data.get("rules"), dict) or delete
    except Exception as e:
        raise ValueError(f"사전 파일을 고치지 못했습니다(형식 오류): {e}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return {"ok": True}
