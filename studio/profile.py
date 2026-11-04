"""작업 종류별 문구 — 화면·대본·썸네일·유튜브 설명에 들어가는 말을 한 곳에서.

  g9    국가직 9급 기출(인사혁신처 원문·최종정답) — 원래 스튜디오의 기본
  mock  자사 모의고사(xam-local2 `07/mNN/` 의 1단 46배판 시험지·정답표·대본) — 회차 × 과목 = 영상 한 편(20문항)

job.json 의 "kind" 로 고른다(없으면 g9).
"""
from __future__ import annotations

from typing import Any, Dict

NUM_KO = {20: "스무", 10: "열", 40: "마흔"}


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


def _mock(m: Dict[str, Any]) -> Dict[str, Any]:
    subj, exam = m["subject"], m["exam"]          # 예: 스프레드시트 일반 · 컴퓨터활용능력 2급 필기
    short = m.get("short") or exam                  # 예: 컴활 2급
    rl = m["round_label"]                           # 예: 06회
    lo, hi = m["range"]
    n = hi - lo + 1
    n_ko = NUM_KO.get(n, str(n))
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
        "tags": [short, exam, f"{short} 필기", f"{short} {subj}", "컴활 모의고사", "컴활 2급 필기 기출", "필기 해설"],
        "thumb_line1": f"{rl} {subj}", "thumb_line2": f"모의고사 {n}문항 해설", "thumb_num": rl.replace("회", ""),
        "thumb_tag": f"{short} 필기 · 문항별 챕터",
        "playlist": f"{short} 필기 모의고사 해설",
        "prompt_role": f"{exam} 시험 전문 강사",
        "prompt_head": f"{short} 필기 모의고사 {rl} {subj} {{no}}번",
        "prompt_basis": "정답",
    }
