"""s5 영상: 판서 화면들(frames.json) + 내레이션 + 자막 → 1920×1080 mp4 (ffmpeg 한 번에)

원문 글자를 읽어야 하므로 줌·팬 없이, 판서가 그려지는 컷만 바뀐다.
  ① concat 리스트: frames.json 의 화면과 길이
  ② 자막: timing.cues → ASS (Pretendard SemiBold, 아래 자막 띠, 두 줄까지 나눠 표시)
  ③ ffmpeg: concat 이미지 + narration.wav + subtitles → libx264 (-tune stillimage)
결과: out/<id>.mp4, out/contact_01.jpg(검수용 모아보기), out/chapters.txt(유튜브 챕터)
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List

from . import FONTS
from .job import Job, read_json
from .log import log

FPS, CRF = 30, 20
CAP_SIZE, CAP_MARGIN, MAX_LINE = 54, 70, 30


def ffmpeg() -> str:
    exe = shutil.which("ffmpeg")
    if not exe:
        raise RuntimeError("ffmpeg 가 없습니다 — `winget install Gyan.FFmpeg` 후 새 창에서 다시 실행하세요")
    return exe


def _ts(sec: float) -> str:
    sec = max(0.0, sec)
    h, m = int(sec // 3600), int(sec % 3600 // 60)
    return f"{h}:{m:02d}:{sec % 60:05.2f}"


def _esc(s: str) -> str:
    return s.replace("\\", "＼").replace("{", "(").replace("}", ")").replace("\n", " ")


def _wrap(text: str, width: int = MAX_LINE) -> List[str]:
    """공백에서만 끊어 width 안팎의 줄로."""
    words, lines, cur = text.split(), [], ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > width:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        lines.append(cur)
    return lines or [text]


def build_ass(timing: Dict[str, Any], path: Path) -> None:
    head = (
        "[Script Info]\nScriptType: v4.00+\nPlayResX: 1920\nPlayResY: 1080\nWrapStyle: 2\nScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
        "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Cap,Pretendard SemiBold,{CAP_SIZE},&H00271811,&H00271811,&H00EEF3F5,&H00000000,0,0,0,0,100,100,0,0,1,3,0,2,120,120,{CAP_MARGIN},1\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    events, cues = [], timing["cues"]
    for i, c in enumerate(cues):
        end = min(cues[i + 1]["start"], c["end"] + 0.6) if i + 1 < len(cues) else c["end"] + 0.6
        lines = _wrap(c["cap"])
        pages = [lines[k:k + 2] for k in range(0, len(lines), 2)]
        total = sum(len(" ".join(p)) for p in pages) or 1
        t = c["start"]
        for p in pages:
            dur = (end - c["start"]) * len(" ".join(p)) / total
            text = r"\N".join(_esc(x) for x in p)
            events.append(f"Dialogue: 0,{_ts(t)},{_ts(t + dur)},Cap,,0,0,0,,{text}")
            t += dur
    path.write_text(head + "\n".join(events) + "\n", encoding="utf-8-sig")


def run(job: Job, force: bool = False) -> Path:
    timing = read_json(job.audio / "timing.json")
    if not timing:
        raise RuntimeError("timing.json 이 없습니다 — s3 를 먼저 실행하세요")
    out = job.out
    work = out / "_work"
    work.mkdir(parents=True, exist_ok=True)
    frames = read_json(job.boards / "frames.json")
    if not frames:
        raise RuntimeError("frames.json 이 없습니다 — 화면(s4)을 먼저 실행하세요")
    import hashlib, json as _json
    stamp = f"{timing['hash']}|{FPS}|{CRF}|{CAP_SIZE}|" + hashlib.sha1(_json.dumps(frames).encode()).hexdigest()[:12]
    if job.video.exists() and (work / "stamp.txt").exists() and (work / "stamp.txt").read_text() == stamp and not force:
        log("s5 영상: 바뀐 것 없음 — 건너뜀")
        return job.video

    # ① 이미지 목록 (concat demuxer 는 마지막 파일을 한 번 더 적어야 길이가 반영된다)
    lst = []
    for fr in frames:
        img = (job.boards / fr["img"]).resolve().as_posix().replace("'", "'\\''")
        lst += [f"file '{img}'", f"duration {fr['dur']:.3f}"]
    lst.append(lst[-2])
    (work / "boards.txt").write_text("\n".join(lst) + "\n", encoding="utf-8")
    # ② 자막 + 글꼴
    build_ass(timing, work / "captions.ass")
    fonts = work / "fonts"
    fonts.mkdir(exist_ok=True)
    for f in FONTS.glob("*.*tf"):
        shutil.copy2(f, fonts / f.name)
    # ③ 굽기
    log(f"s5 영상 굽는 중 ({int(timing['duration'] // 60)}분 {int(timing['duration'] % 60)}초 분량)…")
    tmp = out / f"{job.id}.part.mp4"
    cmd = [ffmpeg(), "-y", "-hide_banner", "-loglevel", "error",
           "-f", "concat", "-safe", "0", "-i", "boards.txt", "-i", str((job.audio / "narration.wav").resolve()),
           "-vf", f"fps={FPS},scale=1920:1080,subtitles=captions.ass:fontsdir=fonts,format=yuv420p",
           "-c:v", "libx264", "-preset", "medium", "-tune", "stillimage", "-crf", str(CRF),
           "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", str(tmp.resolve())]
    proc = subprocess.run(cmd, cwd=work, capture_output=True, encoding="utf-8", errors="replace",
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg 실패: {proc.stderr[-1200:]}")
    tmp.replace(job.video)
    # 검수용 모아보기 (10초마다 한 컷)
    subprocess.run([ffmpeg(), "-y", "-hide_banner", "-loglevel", "error", "-i", str(job.video),
                    "-vf", "fps=1/10,scale=384:-2,tile=6x8:padding=4:margin=8:color=white", str(out / "contact_%02d.jpg")],
                   capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    (out / "chapters.txt").write_text("\n".join(chapter_lines(timing)) + "\n", encoding="utf-8")
    (work / "stamp.txt").write_text(stamp)
    job.mark("s5", mb=round(job.video.stat().st_size / 1e6, 1))
    log(f"s5 영상 완료: {job.video.name} ({job.video.stat().st_size / 1e6:.0f}MB)")
    return job.video


def chapter_lines(timing: Dict[str, Any]) -> List[str]:
    """유튜브 챕터(설명란): 0:00 시작, 3개 이상, 각 10초 이상"""
    def ts(sec: float) -> str:
        sec = int(sec)
        return f"{sec // 3600}:{sec % 3600 // 60:02d}:{sec % 60:02d}" if sec >= 3600 else f"{sec // 60}:{sec % 60:02d}"
    rows = [(0 if i == 0 else c["start"], c["title"]) for i, c in enumerate(timing["chapters"])]
    if len(rows) < 3 or any(b[0] - a[0] < 10 for a, b in zip(rows, rows[1:])):
        return []
    return [f"{ts(t)} {title}" for t, title in rows]
