"""s1 대본: Claude CLI 가 문항별 해설 내레이션 + 이북 해설 글을 쓴다.

- 정답은 공식 최종정답으로 고정해서 넘긴다(바꾸지 못하게 검사).
- 문항 이미지(문제판)를 Read 도구로 직접 보게 해 그림·표·코드 문항도 정확히 읽는다.
- **문항마다 script/qNN.json 으로 저장(체크포인트)** → 한도 소진·프로그램 종료 후 다시 실행하면 끝난 문항은 건너뛴다.
- 인트로·마무리·유튜브 문구는 템플릿(토큰을 쓰지 않음).
"""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any, Dict, List, Optional

from . import profile, claude
from .job import Job, read_json, write_json
from .log import log

CIRCLED = "①②③④⑤"
MAX_SAY = 80
WORKERS = 3

PROMPT = """너는 {role}다. 유튜브 해설 영상의 내레이션 대본과 이북용 해설을 쓴다.

[문항] {head}
문항 이미지 파일: {image}
→ 먼저 Read 도구로 이 이미지를 열어 문항(그림·표·코드 포함)을 정확히 읽어라.
참고용 추출 텍스트(띄어쓰기가 깨졌을 수 있음):
<<<
{text}
>>>

[{basis}] {answer_text}  ← 절대 바꾸지 말 것. 해설은 이 정답이 왜 맞는지, 나머지 보기가 왜 틀린지를 설명한다.

[출력] 아래 JSON 하나만 출력한다. 다른 말은 쓰지 않는다.
{{
  "chapter_title": "{no}번 · (핵심 주제 8~14자)",
  "read":   [{{"say": "…", "cap": "…"}}],          // 1~2문장: 무엇을 묻는 문제인지 짧게 소개 (문항을 통째로 읽지 말 것)
  "solve":  [{{"say": "…", "cap": "…"}}, …],       // 4~8문장: 핵심 개념 → 보기별 판단(“1번 보기는 …”)
  "answer": [{{"say": "…", "cap": "…"}}],          // 1~2문장: "따라서 정답은 N번입니다." + 한 줄 정리
  "keywords": ["…", "…", "…"],                     // 핵심어 2~4개
  "solution_md": "**정답 {answer_mark}**\\n\\n### 핵심 개념\\n…\\n\\n### 풀이\\n…\\n\\n### 오답 체크\\n- ① …\\n- ② …"
}}

[규칙]
- say: 읽어 줄 문장. 합니다체. 한 문장 {max_say}자 이내. 보기는 "1번 보기"처럼 숫자로 말한다(①② 기호 금지).
  영문 약어는 그대로 써도 된다(읽기 변환은 프로그램이 함). 수식·코드는 말로 풀어 쓴다.
- cap: 화면 자막. say 를 줄인 말(28자 이내 권장, 최대 40자).
- 전체 say 분량 250~450자(약 45~75초).
- 사실이 불확실하면 단정하지 말고 개념 위주로 설명한다. 지어낸 출처·수치를 쓰지 않는다.
- solution_md 는 Markdown, 수식은 $…$, 600자 이내.
"""


def _answer_text(ans: List[int]) -> str:
    return ", ".join(f"{a}번({CIRCLED[a - 1]})" for a in ans) + (" (복수 정답 인정)" if len(ans) > 1 else "")


def _validate(d: Dict[str, Any], no: int, ans: List[int]) -> Optional[str]:
    for key in ("read", "solve", "answer"):
        lines = d.get(key)
        if not isinstance(lines, list) or not lines:
            return f"{key} 가 비었습니다"
        for ln in lines:
            if not isinstance(ln, dict) or not str(ln.get("say", "")).strip():
                return f"{key} 문장 형식 오류"
            if len(ln["say"]) > MAX_SAY * 1.6:
                return f"{key} 문장이 너무 깁니다({len(ln['say'])}자)"
    said = " ".join(ln["say"] for ln in d["answer"])
    if not any(re.search(rf"(?<!\d){a}\s*번", said) for a in ans):
        return f"정답 문장에 '{ans[0]}번'이 없습니다"
    wrong = [n for n in re.findall(r"정답은\s*(\d)\s*번", said) if int(n) not in ans]
    if wrong:
        return f"정답과 다른 번호를 말합니다({wrong})"
    total = sum(len(ln["say"]) for k in ("read", "solve", "answer") for ln in d[k])
    if not 150 <= total <= 700:
        return f"분량이 맞지 않습니다({total}자)"
    if CIRCLED[ans[0] - 1] not in str(d.get("solution_md", "")):
        return "solution_md 에 정답 기호가 없습니다"
    return None


def _one(job: Job, q: Dict[str, Any], quiz: Dict[str, Any], force: bool) -> Dict[str, Any]:
    no = q["no"]
    path = job.scripts / f"q{no:02d}.json"
    if path.exists() and not force:
        return read_json(path)
    m = job.meta
    ans = quiz["answers"]
    image = (job.boards / f"crop/q{no:02d}.png").resolve()
    tx = profile.texts(m)
    prompt = PROMPT.format(role=tx["prompt_role"], head=tx["prompt_head"].format(no=no), basis=tx["prompt_basis"], no=no,
                           image=str(image).replace("\\", "/"), text=q["text"][:2500], answer_text=_answer_text(ans),
                           answer_mark=", ".join(CIRCLED[a - 1] for a in ans), max_say=MAX_SAY)

    def on_wait(wake: Optional[datetime]) -> None:
        job.update_state(waiting={"until": wake.strftime("%Y-%m-%d %H:%M"), "stage": "s1", "no": no} if wake else None)

    last = ""
    for attempt in range(3):
        extra = f"\n\n[이전 출력의 문제] {last} — 고쳐서 다시 출력하라." if last else ""
        text = claude.ask(prompt + extra, model=m.get("model", "opus"), cwd=job.dir, allow_read=True, on_wait=on_wait)
        try:
            d = claude.extract_json(text)
        except Exception:
            last = "JSON 으로 읽을 수 없습니다"
            continue
        last = _validate(d, no, ans) or ""
        if not last:
            d["no"] = no
            d["answers"] = ans
            write_json(path, d)
            return d
        log(f"  · {no}번 다시 쓰기 ({attempt + 1}): {last}")
    raise RuntimeError(f"{no}번 대본 검사 실패: {last}")


def assemble(job: Job, items: Dict[int, Dict[str, Any]]) -> Dict[str, Any]:
    m = job.meta
    tx = profile.texts(m)
    chapters: List[Dict[str, Any]] = [{
        "title": "시작", "kind": "intro",
        "scenes": [{"board": "intro", "lines": [
            {"say": tx["intro_say"], "cap": tx["intro_cap"]},
            {"say": "문항마다 챕터가 나뉘어 있으니 필요한 문항으로 바로 이동해서 보세요.",
             "cap": "문항별 챕터로 바로 이동"},
        ]}],
    }]
    for no in sorted(items):
        d = items[no]
        chapters.append({
            "title": d.get("chapter_title") or f"{no}번", "kind": "quiz", "quiz": no,
            "scenes": [
                {"board": f"q{no:02d}", "part": "read", "lines": d["read"]},
                {"board": f"q{no:02d}", "part": "solve", "lines": d["solve"]},
                {"board": f"q{no:02d}", "part": "answer", "lines": d["answer"]},
            ],
        })
    chapters.append({
        "title": "마무리", "kind": "outro",
        "scenes": [{"board": "outro", "lines": [
            {"say": tx["outro_say"], "cap": tx["outro_cap"]},
            {"say": "틀린 문항은 해설북에서 원문 위에 다시 풀어 보고, 해당 구간 영상으로 복습해 보세요.",
             "cap": "해설북에서 다시 풀고 복습하기"},
        ]}],
    })
    kw = []
    for d in items.values():
        kw += d.get("keywords") or []
    return {
        "id": job.id, "title": m["title"], "chapters": chapters,
        "youtube": {
            "title": tx["yt_title"],
            "hook_lines": [tx["yt_hook"], "설명란 챕터로 원하는 문항부터 바로 보세요."],
            "summary": [tx["yt_basis"],
                        "해설북(이북)에서 원문 위에 필기하며 문항별 해설 구간을 바로 볼 수 있습니다."],
            "tags": list(dict.fromkeys([*tx["tags"], *kw[:12]])),
        },
        "thumbnail": {"line1": tx["thumb_line1"], "line2": tx["thumb_line2"], "keyword": m["subject"]},
    }


def run(job: Job, force: bool = False, only: Optional[List[int]] = None) -> Dict[str, Any]:
    if job.setting("kind") == "mock":
        force = False      # 모의고사 대본의 원본은 xam-local2(07/mNN/script) — 고치려면 거기서 다시 굽고 s0 --force
    questions = read_json(job.book / "questions.json", [])
    # 모의고사는 xam-local2 가 대본(script/qNN.json)을 이미 만들어 둔다 — 모두 있으면 Claude 없이 조립만
    have_all = all((job.scripts / f"q{q['no']:02d}.json").exists() for q in questions)
    if not (have_all and not force) and not claude.available():
        raise RuntimeError("claude CLI 가 없습니다 — Claude Code 설치 후 `claude auth login`")
    quizzes = {q["no"]: q for q in read_json(job.book / "quizzes.json", [])}
    if not (job.boards / "boards.json").exists():
        raise RuntimeError("문항 크롭이 없습니다 — 원문 준비(s0)를 먼저 실행하세요")
    job.scripts.mkdir(parents=True, exist_ok=True)
    todo = [q for q in questions if (only is None or q["no"] in only)]
    done_before = sum(1 for q in todo if (job.scripts / f"q{q['no']:02d}.json").exists() and not force)
    log(f"s1 대본: {len(todo)}문항 (이미 끝난 {done_before}문항은 건너뜀, 동시 {WORKERS}개)")
    items: Dict[int, Dict[str, Any]] = {}
    with ThreadPoolExecutor(WORKERS) as pool:
        futs = {pool.submit(_one, job, q, quizzes[q["no"]], force): q["no"] for q in todo}
        for f in as_completed(futs):
            no = futs[f]
            items[no] = f.result()
            log(f"  ✓ {no}번 대본 ({len(items)}/{len(todo)})")
    for q in questions:  # --only 로 일부만 다시 쓴 경우 나머지는 저장본으로
        items.setdefault(q["no"], read_json(job.scripts / f"q{q['no']:02d}.json"))
    if any(v is None for v in items.values()):
        raise RuntimeError("대본이 없는 문항이 있습니다")
    script = assemble(job, items)
    write_json(job.dir / "script.json", script)
    write_json(job.book / "solutions.json", [{"no": no, "markdown": d["solution_md"]} for no, d in sorted(items.items())])
    qz = read_json(job.book / "quizzes.json", [])
    for q in qz:
        q["keywords"] = (items[q["no"]].get("keywords") or [])[:4]
    write_json(job.book / "quizzes.json", qz)
    job.update_state(waiting=None)
    job.mark("s1")
    log("s1 대본 완료 → script.json, book/solutions.json")
    return script
