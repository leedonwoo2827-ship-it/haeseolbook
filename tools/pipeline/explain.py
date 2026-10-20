"""문항별 해설 초안 생성 (DeepSeek, 필요할 때만)

  set DEEPSEEK_API_KEY=sk-...        (키는 환경변수로만 받는다. 파일·저장소에 저장하지 않는다)
  python -I tools/pipeline/explain.py content/build/2025-g9-electric [--model deepseek-chat] [--only 3,7]

입력: questions.json(문항 텍스트), quizzes.json(공식 정답)
출력: solutions.draft.json  → 사람이 검수해 solutions.json 으로 확정한 뒤 seed 한다.

정답은 공식 정답표를 넣어 주고 LLM 에게는 "왜 그 답인지"만 쓰게 해 환각을 줄인다.
키가 없으면 아무것도 하지 않고 종료한다(해설은 수기 또는 exambook-forge 로 작성).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import requests

API_URL = "https://api.deepseek.com/chat/completions"
SYSTEM = (
    "당신은 9급 국가직 기술직 공무원 시험 전문 강사입니다. "
    "주어진 문항과 공식 정답을 바탕으로 수험생용 해설을 한국어 Markdown 으로 작성합니다. "
    "정답을 바꾸지 마십시오. 형식: '**정답 ③**' 한 줄, '### 핵심 개념' (2~4줄), '### 풀이' (단계별, 수식은 $...$), "
    "'### 오답 체크' (보기별 한 줄). 600자 이내. 문항 원문을 그대로 옮겨 적지 마십시오."
)
CIRCLED = "①②③④⑤"


def ask(key: str, model: str, question: str, answer: int, retries: int = 3) -> str:
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": f"[문항]\n{question}\n\n[공식 정답] {CIRCLED[answer - 1]}"},
        ],
        "temperature": 0.3,
        "max_tokens": 1200,
    }
    for attempt in range(retries):
        try:
            r = requests.post(API_URL, json=body, headers={"Authorization": f"Bearer {key}"}, timeout=120)
            if r.status_code == 429 or r.status_code >= 500:
                raise RuntimeError(f"HTTP {r.status_code}")
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"].strip()
        except Exception as e:  # noqa: BLE001 — 재시도 후 마지막 오류를 올린다
            if attempt == retries - 1:
                raise
            print(f"    retry ({e})", file=sys.stderr)
            time.sleep(2 ** attempt * 3)
    raise AssertionError


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("build", type=Path)
    ap.add_argument("--model", default="deepseek-chat", help="계산형 문항은 deepseek-reasoner 권장")
    ap.add_argument("--only", help="쉼표로 구분한 문항 번호만")
    a = ap.parse_args()

    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not key:
        print("DEEPSEEK_API_KEY 가 없어 해설 자동 생성을 건너뜁니다.")
        return

    questions = {q["no"]: q for q in json.loads((a.build / "questions.json").read_text(encoding="utf-8"))}
    answers = {q["no"]: q["answer"] for q in json.loads((a.build / "quizzes.json").read_text(encoding="utf-8"))}
    only = {int(x) for x in a.only.split(",")} if a.only else None

    out_file = a.build / "solutions.draft.json"
    drafts = {d["no"]: d for d in json.loads(out_file.read_text(encoding="utf-8"))} if out_file.exists() else {}
    for no in sorted(questions):
        if (only and no not in only) or (not only and no in drafts):
            continue
        if no not in answers:
            print(f"  {no}번: 정답 없음, 건너뜀", file=sys.stderr)
            continue
        print(f"  {no}번 해설 생성…", file=sys.stderr)
        drafts[no] = {"no": no, "markdown": ask(key, a.model, questions[no]["text"], answers[no]), "model": a.model, "reviewed": False}
        out_file.write_text(json.dumps(sorted(drafts.values(), key=lambda d: d["no"]), ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(drafts)} drafts → {out_file}  (검수 후 solutions.json 으로 저장)")


if __name__ == "__main__":
    main()
