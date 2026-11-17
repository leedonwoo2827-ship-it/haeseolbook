"""작업 종류별 문구 — 화면·대본·썸네일·유튜브 설명에 들어가는 말을 한 곳에서.

  g9    국가직 9급 기출(인사혁신처 원문·최종정답) — 원래 스튜디오의 기본
  mock  자사 모의고사(xam-local3 `07/mNN/` 의 1단 46배판 시험지·정답표·대본) — 회차 × 과목 = 영상 한 편(20문항)

job.json 의 "kind" 로 고른다(없으면 g9).
"""
from __future__ import annotations

from typing import Any, Dict

NUM_KO = {20: "스무", 10: "열", 40: "마흔", 50: "쉰"}


def texts(m: Dict[str, Any]) -> Dict[str, Any]:
    if m.get("kind") == "mock":
        return _mock(m)
    year, subj, exam = m["year"], m["subject"], m["exam"]
    return {
        "intro_say": f"{year}년 {exam} {subj} 기출문제 스무 문항을 처음부터 끝까지 풀어 보겠습니다.",
        "intro_cap": f"{year} {exam} {subj} 기출 20문항",
        "outro_say": f"이것으로 {year}년 {subj} 스무 문항 해설을 마칩니다.",
        "outro_cap": "20문항 해설 끝",
        "title_big": f"{year} {subj}", "title_second": f"{exam} 기출 20문항 해설",
        "title_small": "원문: 인사혁신처 공개 기출 · 최종정답 기준", "title_num": str(year),
        "yt_title": f"{year} {exam} {subj} 기출 해설 | 20문항 전체 풀이 (문항별 챕터)",
        "yt_hook": f"{year}년 {exam} {subj} 20문항을 원문 그대로 보며 한 문항씩 풀이합니다.",
        "yt_basis": "정답은 인사혁신처 최종정답 기준입니다.",
        "tags": [f"{exam}", f"{subj}", f"{year} {subj}", "공무원 기출", "9급 전산직", "기출 해설"],
        "thumb_line1": f"{year} {subj}", "thumb_line2": "기출 20문항 해설", "thumb_num": str(year),
        "thumb_tag": f"{exam} · 문항별 챕터",
        "playlist": f"{exam} {subj} 기출 해설",
        "prompt_role": f"9급 국가직 {subj} 시험 전문 강사",
        "prompt_head": f"{year}년 {exam} {subj} {{no}}번 ({m.get('booklet', '')}책형)",
        "prompt_basis": "공식 최종정답",
    }


_ONES = ["", "한", "두", "세", "네", "다섯", "여섯", "일곱", "여덟", "아홉"]
_TENS = ["", "열", "스물", "서른", "마흔", "쉰", "예순", "일흔", "여든", "아흔"]


def count_ko(n: int) -> str:
    """문항 수를 고유어로 — 12 → 열두, 20 → 스무, 25 → 스물다섯 (99까지)"""
    if n == 20:
        return "스무"
    if not 0 < n < 100:
        return str(n)
    return _TENS[n // 10] + _ONES[n % 10]


def _lecture(m: Dict[str, Any]) -> Dict[str, Any]:
    """3부 강 행 — 11~15회 문항을 1부 강의(종합반) 강마다 모은 한 편. 사이트의 「강별 출제예상문제반」
    보이는 곳(화면·자막·낭독·썸네일·유튜브 제목/설명)에는 「N강」만 — 강 제목·원래 회차·번호는 쓰지 않는다
    (게시판이 강별로 나뉜다. 사용자 2026-11-15). 강 제목은 보이지 않는 태그에만."""
    subj, exam = m["subject"], m["exam"]
    short = m.get("short") or exam
    lid, lt, n = m["lecture"], m["lecture_title"], len(m.get("questions") or [])
    ln = int(m.get("lecture_no") or lid[1:])
    return {
        "intro_say": f"{short} 출제 예상 문제 {ln}강, {count_ko(n)} 문항을 풀어 보겠습니다.",
        "intro_cap": f"{short} 출제예상문제 {ln}강 · {n}문항",
        "outro_say": f"이것으로 {ln}강 {count_ko(n)} 문항 풀이를 마칩니다.",
        "outro_cap": f"{ln}강 {n}문항 풀이 끝",
        "title_big": f"{ln}강", "title_second": f"{short} 출제예상문제 · {subj}",
        "title_small": f"1~{n}번 · {n}문항 풀이 · 문항별 챕터",
        "title_num": f"{ln:02d}",
        "yt_title": f"{short} 필기 출제예상문제 {ln}강 | {n}문항 풀이 (문항별 챕터)",
        "yt_hook": f"{short} 필기 출제예상문제 {ln}강, {n}문항을 한 문항씩 풀이합니다.",
        "yt_basis": "자체 집필 문항입니다.",
        "tags": [short, exam, f"{short} 필기", f"{short} {subj}", f"{short} 출제예상문제", lt, "필기 해설"],
        "thumb_big": f"{ln}강", "thumb_line1": f"{ln}강", "thumb_line2": subj,
        "thumb_num": f"{ln:02d}",
        "thumb_tag": f"{short} 필기 출제예상문제",
        "playlist": f"{short} 필기 출제예상문제(강별)",
        "prompt_role": f"{exam} 시험 전문 강사",
        "prompt_head": f"{short} 출제예상문제 {ln}강 {{no}}번",
        "prompt_basis": "정답",
    }


def _mock(m: Dict[str, Any]) -> Dict[str, Any]:
    if m.get("unit") == "lecture":
        return _lecture(m)
    subj, exam = m["subject"], m["exam"]          # 예: 스프레드시트 일반 · 컴퓨터활용능력 2급 필기
    short = m.get("short") or exam                  # 예: 컴활 2급
    rl = m["round_label"]                           # 예: 06회
    lo, hi = m["range"]
    n = hi - lo + 1
    n_ko = NUM_KO.get(n, str(n))
    if m.get("no_dest"):
        return _mock_plain(m, short, rl, lo, hi, n, n_ko)
    return {
        "intro_say": f"{short} 필기 모의고사 {rl}, {subj} {n_ko} 문항을 처음부터 끝까지 풀어 보겠습니다.",
        "intro_cap": f"{short} 모의고사 {rl} · {subj} {n}문항",
        "outro_say": f"이것으로 {rl} {subj} {n_ko} 문항 해설을 마칩니다.",
        "outro_cap": f"{n}문항 해설 끝",
        "title_big": f"{rl} {subj}", "title_second": f"{short} 모의고사 {n}문항 해설",
        "title_small": f"{lo}~{hi}번 · " + ("교재 수록 회차" if m.get("dest") == "textbook" else "이북 전용 회차"),
        "title_num": rl.replace("회", ""),
        "yt_title": f"{short} 필기 모의고사{'' if m.get('dest') == 'textbook' else '(이북)'} {rl} {subj} 해설 | {lo}~{hi}번 {n}문항 풀이 (문항별 챕터)",
        "yt_hook": f"{short} 필기 모의고사 {rl} {subj} {n}문항을 시험지 그대로 보며 한 문항씩 풀이합니다.",
        "yt_basis": "자체 집필 모의고사입니다. 시험지·정답·해설은 교재와 해설북(이북)에 있습니다.",
        "tags": [short, exam, f"{short} 필기", f"{short} {subj}", f"{short.split()[0]} 모의고사", f"{short} 필기 기출", "필기 해설"],
        "thumb_line1": f"{rl} {subj}", "thumb_line2": f"모의고사 {n}문항 해설", "thumb_num": rl.replace("회", ""),
        "thumb_tag": f"{short} 필기 · 문항별 챕터",
        "playlist": f"{short} 필기 모의고사 해설",
        "prompt_role": f"{exam} 시험 전문 강사",
        "prompt_head": f"{short} 필기 모의고사 {rl} {subj} {{no}}번",
        "prompt_basis": "정답",
    }


def _mock_plain(m: Dict[str, Any], short: str, rl: str, lo: int, hi: int, n: int, n_ko: str) -> Dict[str, Any]:
    """교재/이북 구분 없는 시리즈(SQLD) — 과목을 10문항씩 나눠 편마다 번호 범위로 구별. 「이북」이라는 말을 쓰지 않는다"""
    subj, exam = m["subject"], m["exam"]
    rn = rl[:-1].lstrip("0") + "회" if rl.endswith("회") and rl[:-1].isdigit() else rl   # 자막·낭독은 「1회」(01회 X)
    return {
        "intro_say": f"{short} 필기 모의고사 {rn}, {subj} {n_ko} 문항을 풀어 보겠습니다.",
        "intro_cap": f"{short} 모의고사 {rn} · {subj} {lo}~{hi}문항",
        "outro_say": f"이것으로 {rn} {subj} {n_ko} 문항 해설을 마칩니다.",
        "outro_cap": f"{lo}~{hi}문항 해설 끝",
        "title_big": f"{rl} {lo}~{hi}번", "title_second": f"{short} 모의고사 · {subj}",
        "title_small": f"{n}문항 해설 · 문항별 챕터",
        "title_num": rl.replace("회", ""),
        "yt_title": f"{short} 필기 모의고사 {rl} {lo}~{hi}번 {subj} 해설 | {n}문항 풀이 (문항별 챕터)",
        "yt_hook": f"{short} 필기 모의고사 {rl} {lo}~{hi}번({subj})을 시험지 그대로 보며 한 문항씩 풀이합니다.",
        "yt_basis": "자체 집필 모의고사입니다.",
        "tags": [short, exam, f"{short} 필기", f"{short} {subj}", f"{short} 모의고사", f"{short} 기출", "필기 해설"],
        "thumb_big": f"{lo}~{hi}번", "thumb_line1": f"{rl} {lo}~{hi}번", "thumb_line2": subj,
        "thumb_num": rl.replace("회", ""),
        "thumb_tag": f"{short} 필기 모의고사 {rl}",
        "playlist": f"{short} 필기 모의고사 해설",
        "prompt_role": f"{exam} 시험 전문 강사",
        "prompt_head": f"{short} 필기 모의고사 {rl} {subj} {{no}}번",
        "prompt_basis": "정답",
    }
