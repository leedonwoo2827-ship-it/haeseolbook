"""s3 목소리: 대본 문장별 SuperTonic3 합성 → narration.wav + timing.json

- 문장 캐시: audio/lines/<sha1(발음 사전 적용 후 문장, 목소리, 속도)>.wav — 사전을 고치면 그 문장만 다시 — 고친 문장만 다시 합성(중단 후 이어서도 그대로 재사용)
- 무음: 시작 0.6s · 같은 씬 문장 사이 0.35s · 씬이 바뀌면 0.8s · 끝 1.5s
- timing.json: {duration, voice, speed, hash, cues:[{i,scene,chapter,cap,start,end}], scenes:[{n,chapter,board,start,end}], chapters:[{i,title,quiz,start}]}
"""
from __future__ import annotations

import hashlib
import wave
from typing import Any, Dict, List

import numpy as np

from .job import Job, read_json, write_json
from .log import log
from .tts import engine

LEAD, GAP, SCENE_GAP, TAIL = 0.6, 0.35, 0.8, 1.5


def flatten(script: Dict[str, Any]) -> List[Dict[str, Any]]:
    """장 → 씬 → 문장을 한 줄로 (씬 번호는 전체에서 1부터)."""
    out, n = [], 0
    for ci, ch in enumerate(script["chapters"], start=1):
        for sc in ch["scenes"]:
            n += 1
            for ln in sc["lines"]:
                out.append({"chapter": ci, "scene": n, "board": sc["board"], "say": (ln.get("say") or ln.get("cap") or "…").strip(),
                            "cap": (ln.get("cap") or ln.get("say") or "").strip()})
    return out


def _read_wav(path) -> np.ndarray:
    with wave.open(str(path), "rb") as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32767.0


def run(job: Job, force: bool = False) -> Dict[str, Any]:
    script = job.script()
    if not script:
        raise RuntimeError("대본이 없습니다 — s2 를 먼저 실행하세요")
    voice, speed = job.setting("voice", "F1"), float(job.setting("speed", 1.0))
    items = flatten(script)
    eng = engine.Engine.get()
    # 캐시 기준 = 실제로 읽는 발음(사전 적용 후) — 발음 사전을 고치면 그 문장만 다시 합성된다
    spoken = lambda t: eng._pmap.apply(t, spell_unknown_acronyms=True, convert_years=True)   # noqa: E731
    for it in items:
        it["spoken"] = spoken(it["say"])
    key = hashlib.sha1(repr([(i["spoken"], i["scene"]) for i in items] + [voice, speed, LEAD, GAP, SCENE_GAP, TAIL]).encode()).hexdigest()[:16]
    tpath, npath = job.audio / "timing.json", job.audio / "narration.wav"
    old = read_json(tpath)
    if old and old.get("hash") == key and npath.exists() and not force:
        log("s3 목소리: 바뀐 문장 없음 — 건너뜀")
        return old

    sr = eng.sample_rate
    lines_dir = job.audio / "lines"
    lines_dir.mkdir(parents=True, exist_ok=True)
    new = 0
    for idx, it in enumerate(items):
        h = hashlib.sha1(f"{it['spoken']}|{voice}|{speed}".encode()).hexdigest()[:16]
        it["file"] = lines_dir / f"{h}.wav"
        if not it["file"].exists():
            engine.write_wav(it["file"], eng.synth(it["say"], voice=voice, speed=speed), sr)
            new += 1
            if new % 20 == 0:
                log(f"  합성 {idx + 1}/{len(items)}")
    log(f"s3 목소리: 문장 {len(items)}개 (새로 합성 {new}개, 목소리 {voice})")

    pieces: List[np.ndarray] = []
    t = 0.0

    def silence(sec: float) -> None:
        nonlocal t
        pieces.append(np.zeros(int(sr * sec), dtype=np.float32))
        t += sec

    cues, prev_scene = [], None
    silence(LEAD)
    for i, it in enumerate(items):
        if prev_scene is not None:
            silence(SCENE_GAP if it["scene"] != prev_scene else GAP)
        wav = _read_wav(it["file"])
        start = t
        pieces.append(wav)
        t += len(wav) / sr
        cues.append({"i": i, "scene": it["scene"], "chapter": it["chapter"], "cap": it["cap"], "start": round(start, 3), "end": round(t, 3)})
        prev_scene = it["scene"]
    silence(TAIL)
    duration = round(t, 3)

    scenes: List[Dict[str, Any]] = []
    for c in cues:
        if not scenes or scenes[-1]["n"] != c["scene"]:
            board = next(it["board"] for it in items if it["scene"] == c["scene"])
            start = 0.0 if not scenes else round(c["start"] - SCENE_GAP / 2, 3)
            scenes.append({"n": c["scene"], "chapter": c["chapter"], "board": board, "start": start})
    for a, b in zip(scenes, scenes[1:]):
        a["end"] = b["start"]
    scenes[-1]["end"] = duration
    chapters = []
    for ci, ch in enumerate(script["chapters"], start=1):
        first = next(s for s in scenes if s["chapter"] == ci)
        chapters.append({"i": ci, "title": ch["title"], "quiz": ch.get("quiz"), "start": first["start"]})

    engine.write_wav(npath, np.concatenate(pieces), sr)
    timing = {"duration": duration, "voice": voice, "speed": speed, "hash": key, "cues": cues, "scenes": scenes, "chapters": chapters}
    write_json(tpath, timing)
    job.mark("s3", duration=duration)
    log(f"s3 목소리 완료: {int(duration // 60)}분 {int(duration % 60)}초, 장 {len(chapters)}개")
    return timing
