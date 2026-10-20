"""s2 판서 계획: 대본 문장마다 「원문의 어디에 무엇을 그릴지」를 Claude 가 정한다.

종류: hl(형광펜) · ul(물결 밑줄) · ok(✓) · no(✗) · circle(정답 원)
대상: {"choice": 3} 보기 번호 | {"item": "ㄱ"} 박스 안 항목 | {"text": "전역 변수"} 원문에 그대로 있는 글귀
- 문항마다 script/qNN.marks.json 체크포인트(한도 소진 뒤 이어서).
- 원문에서 위치를 못 찾는 표시는 버린다. 정답 원이 없으면 프로그램이 정답 문장에 붙인다.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any, Dict, List, Optional

import pymupdf as fitz

from . import boards, claude
from .job import Job, read_json, write_json
from .log import log

KINDS = {"hl", "ul", "ok", "no", "circle"}
WORKERS = 3

PROMPT = """너는 강사의 판서(필기)를 설계한다. 원문 문항 위에 강사가 말하는 순간 손으로 표시를 그린다.

문항 이미지: {image}  ← 먼저 Read 로 열어 원문을 확인하라.
원문 추출 텍스트(표시할 글귀는 반드시 여기 나온 글자 그대로 복사):
<<<
{text}
>>>
공식 정답: {answers}

강사 대본(번호가 붙은 문장):
{lines}

[출력] JSON 하나만:
{{"marks": [{{"line": 문장번호, "kind": "hl|ul|ok|no|circle", "target": {{"choice": 보기번호}} 또는 {{"item": "ㄱ"}} 또는 {{"text": "원문 글귀"}}}}]}}

[규칙]
- 그 문장에서 말하는 대상에 표시한다. 한 문장에 0~2개. 문항 전체 4~10개.
- 문제의 핵심 조건·키워드 → hl(형광펜) 또는 ul(밑줄), target 은 text(원문 그대로 4~16자, 줄바꿈 넘지 않게).
- 보기나 ㄱ·ㄴ·ㄷ 항목을 "옳다/맞다" 하면 ok, "틀리다/아니다" 하면 no. target 은 choice 또는 item.
- 정답을 말하는 문장에는 정답 보기에 circle.
- 대본에서 말하지 않은 대상에는 표시하지 않는다.
"""


def _lines(script_q: Dict[str, Any]) -> List[str]:
    return [ln["say"] for part in ("read", "solve", "answer") for ln in script_q[part]]


def _valid(mk: Dict[str, Any], n_lines: int) -> bool:
    t = mk.get("target") or {}
    return (isinstance(mk.get("line"), int) and 0 <= mk["line"] < n_lines and mk.get("kind") in KINDS
            and isinstance(t, dict) and len(t) == 1 and next(iter(t)) in ("choice", "item", "text"))


def _one(job: Job, doc: fitz.Document, no: int, q_text: str, sq: Dict[str, Any], force: bool) -> List[Dict[str, Any]]:
    path = job.scripts / f"q{no:02d}.marks.json"
    if path.exists() and not force:
        return read_json(path)["marks"]
    lines = _lines(sq)
    geo = {"s": 1.0, "ox": 0, "oy": 0, "places": read_json(job.boards / "boards.json")["questions"][str(no)]["places"]}
    image = (job.boards / f"crop/q{no:02d}.png").resolve().as_posix()
    prompt = PROMPT.format(image=image, text=q_text[:2500], answers=", ".join(f"{a}번" for a in sq["answers"]),
                           lines="\n".join(f"{i}. {s}" for i, s in enumerate(lines)))

    def on_wait(wake: Optional[datetime]) -> None:
        job.update_state(waiting={"until": wake.strftime("%Y-%m-%d %H:%M"), "stage": "marks", "no": no} if wake else None)

    marks: List[Dict[str, Any]] = []
    for attempt in range(2):
        text = claude.ask(prompt, model=job.setting("model", "opus"), cwd=job.dir, allow_read=True, on_wait=on_wait)
        try:
            raw = claude.extract_json(text).get("marks") or []
        except Exception:
            continue
        marks = [m for m in raw if _valid(m, len(lines)) and boards.locate(doc, geo, m["target"])]
        if marks or attempt == 1:
            break
    # 정답 원 보장: 정답 문장(answer 의 첫 문장)에 정답 보기 circle
    ans_line = len(sq["read"]) + len(sq["solve"])
    for a in sq["answers"]:
        if not any(m["kind"] == "circle" and m["target"].get("choice") == a for m in marks):
            if boards.locate(doc, geo, {"choice": a}):
                marks.append({"line": ans_line, "kind": "circle", "target": {"choice": a}})
    marks.sort(key=lambda m: m["line"])
    write_json(path, {"no": no, "marks": marks})
    return marks


def run(job: Job, force: bool = False, only: Optional[List[int]] = None) -> None:
    questions = {q["no"]: q for q in read_json(job.book / "questions.json", [])}
    doc = fitz.open(job.paper)
    todo = [no for no in sorted(questions) if only is None or no in only]
    log(f"s2 판서 계획: {len(todo)}문항 (끝난 문항은 건너뜀)")
    with ThreadPoolExecutor(WORKERS) as pool:
        futs = {}
        for no in todo:
            sq = read_json(job.scripts / f"q{no:02d}.json")
            if not sq:
                raise RuntimeError(f"{no}번 대본이 없습니다 — 대본(s1)을 먼저")
            futs[pool.submit(_one, job, doc, no, questions[no]["text"], sq, force)] = no
        for f in as_completed(futs):
            log(f"  ✓ {futs[f]}번 판서 {len(f.result())}개")
    job.update_state(waiting=None)
    job.mark("s2")
