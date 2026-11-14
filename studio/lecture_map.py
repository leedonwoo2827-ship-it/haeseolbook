"""3부 강 행 — 11~20회 문항을 1부 강의(종합반) 강(L01~)마다 나눈 배정표.

근거: 1부 강의 과정(jobs/<lecture_job>/curriculum.json)의 강·절과, 요약집 절마다 적힌 「모의 N회 M번」 인용
(longform.s1_curriculum.load_inputs 가 읽는 refs). 회차·문항 하나는 강 하나에만 들어간다.
  1) 인용한 강 — 여러 강이 인용하면 앞 강
  2) 인용이 없으면 같은 과목 안에서 태그(tags)가 가장 많이 겹치는 강
  3) 그래도 못 정하면 unassigned 로 남긴다 → 사람이 _assets/lecture_map/<code>.json 에서 옮긴다

결과 _assets/lecture_map/<code>.json
  {"code", "lecture_job", "rounds": [11..15], "built": "...",
   "lectures": [{"id": "L01", "no": 1, "title", "subject", "questions": [{"round": 11, "no": 7, "how": "cite|tags|manual"}]}],
   "unassigned": [{"round", "no", "subject", "tags"}]}
사람이 고친 배정(how=manual)은 다시 만들 때도 지킨다.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import ROOT
from .job import mock_series, read_json, write_json

MAPS = ROOT / "_assets" / "lecture_map"


def path(code: str) -> Path:
    return MAPS / f"{code}.json"


def load(code: str) -> Optional[Dict[str, Any]]:
    return read_json(path(code))


def _series(code: str) -> Dict[str, Any]:
    s = next((e for e in mock_series() if e["code"] == code), None)
    if not s or not s.get("lecture_job") or not s.get("lecture_rounds"):
        raise ValueError(f"_assets/mocks.json 의 {code} 에 lecture_job·lecture_rounds 가 없습니다")
    return s


def plain_subject(s: str) -> str:
    """「1과목 · 데이터 모델링의 이해」 → 「데이터 모델링의 이해」"""
    return re.sub(r"^\s*\d+\s*과목\s*[·:\-]\s*", "", s or "").strip()


def build(code: str) -> Dict[str, Any]:
    from longform.config import load_job
    from longform.s1_curriculum import load_inputs

    series = _series(code)
    rounds = [int(x) for x in series["lecture_rounds"]]
    ljob = load_job(series["lecture_job"])
    cur = read_json(ljob.dir / "curriculum.json")
    if not cur:
        raise RuntimeError(f"1부 강의 과정 {series['lecture_job']} 에 curriculum.json 이 없습니다")
    notes, _ = load_inputs(ljob)
    by_id = {s.id: s for n in notes for s in n.sections}

    # 원천 문항(과목·태그) — 책 폴더의 _rounds/mNN.json
    book = Path(series["book"])
    qs: Dict[Tuple[int, int], Dict[str, Any]] = {}
    for r in rounds:
        doc = read_json(book / "_rounds" / f"m{r:02d}.json", {}) or {}
        for q in doc.get("questions") or []:
            qs[(r, int(q["question_no"]))] = {"subject": q.get("subject") or "", "tags": q.get("tags") or []}

    lectures = [{"id": L["id"], "no": L["no"], "title": L["title"], "subject": plain_subject(L.get("subject", "")),
                 "questions": []} for L in cur["lectures"]]
    owner: Dict[Tuple[int, int], Tuple[str, str]] = {}

    old = load(code) or {}                       # 사람이 옮긴 것(manual)은 그대로
    for L in old.get("lectures") or []:
        for q in L.get("questions") or []:
            if q.get("how") == "manual":
                owner[(int(q["round"]), int(q["no"]))] = (L["id"], "manual")

    for L in cur["lectures"]:                    # 1) 인용
        for sd in L["sections"]:
            s = by_id.get(sd["id"])
            if not s:
                continue
            for r in list(s.refs) + [x for sub in s.subs for x in sub.refs]:
                k = (int(r[0]), int(r[1]))
                if k in qs and k not in owner:
                    owner[k] = (L["id"], "cite")

    tags_of: Dict[str, set] = {L["id"]: set() for L in lectures}
    for k, (lid, _) in owner.items():
        tags_of[lid].update(qs[k]["tags"])
    subj_of = {L["id"]: L["subject"] for L in lectures}
    unassigned: List[Dict[str, Any]] = []
    for k in sorted(qs):                         # 2) 태그
        if k in owner:
            continue
        q = qs[k]
        cands = [(len(tags_of[lid] & set(q["tags"])), lid) for lid in tags_of
                 if subj_of[lid] == q["subject"] and tags_of[lid] & set(q["tags"])]
        if cands:
            owner[k] = (max(cands, key=lambda c: (c[0], -int(c[1][1:])))[1], "tags")
        else:
            unassigned.append({"round": k[0], "no": k[1], **q})

    by_lid = {L["id"]: L for L in lectures}
    for k in sorted(owner):
        lid, how = owner[k]
        if lid in by_lid:
            by_lid[lid]["questions"].append({"round": k[0], "no": k[1], "how": how})
    out = {"code": code, "lecture_job": series["lecture_job"], "rounds": rounds,
           "built": time.strftime("%Y-%m-%d %H:%M"), "lectures": lectures, "unassigned": unassigned}
    write_json(path(code), out)
    return out


def summary(m: Dict[str, Any]) -> str:
    n = sum(len(L["questions"]) for L in m["lectures"])
    how: Dict[str, int] = {}
    for L in m["lectures"]:
        for q in L["questions"]:
            how[q["how"]] = how.get(q["how"], 0) + 1
    lines = [f"{m['code']}: {m['rounds'][0]}~{m['rounds'][-1]}회 {n}문항 → {len(m['lectures'])}강 "
             f"({', '.join(f'{k} {v}' for k, v in sorted(how.items()))}) · 못 정함 {len(m['unassigned'])}"]
    lines += [f"  {L['id']} {L['title']} — {len(L['questions'])}문항" for L in m["lectures"]]
    lines += [f"  ? {u['round']}회 {u['no']}번 {u['subject']} {u['tags']}" for u in m["unassigned"]]
    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    print(summary(build(sys.argv[1] if len(sys.argv) > 1 else "sqld")))
