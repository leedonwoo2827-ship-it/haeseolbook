"""Claude CLI(구독) 호출 — 사용 한도에 걸리면 리셋 시각까지 기다렸다가 같은 요청을 다시 보낸다.

한도 메시지 예:
  "Claude AI usage limit reached|1760943600"              (리셋 epoch)
  "You've hit your limit · resets 3pm (Asia/Seoul)"
  "5-hour limit reached ∙ resets 11:30pm"
리셋 시각을 읽지 못하면 15분 간격으로 다시 시도한다. 기다리는 동안 job state 에 `waiting` 을 남겨 대시보드에 보인다.
작업 쪽은 문항 단위로 결과를 저장(체크포인트)하므로, 프로그램이 꺼졌다가 다시 실행해도 끝난 문항은 건너뛴다.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Optional

from .log import log

LIMIT_RE = re.compile(r"usage limit|limit reached|hour limit|weekly limit|hit your limit|rate.?limit|overloaded|"
                      r"too many requests|resets? (?:at )?\d|(?<!\d)(?:429|529)(?!\d)|한도", re.I)
EPOCH_RE = re.compile(r"\|(\d{10})\b")
CLOCK_RE = re.compile(r"resets?\s+(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", re.I)
RETRY_SEC = 30 * 60          # 재설정 시각을 모를 때 다시 확인하는 간격
CHUNK_SEC = 60 * 60          # 재설정 시각을 알아도 최대 이만큼씩 자고 다시 확인(주간 한도가 일찍 풀리는 경우)
MAX_WAIT_HOURS = 24


class ClaudeError(RuntimeError):
    pass


def keep_awake(on: bool = True) -> None:
    """기다리는 동안 Windows 가 절전에 들어가지 않게(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)."""
    import os
    if os.name != "nt":
        return
    try:
        import ctypes
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | (0x00000001 if on else 0))
    except Exception:
        pass


def available() -> bool:
    return shutil.which("claude") is not None


def _reset_at(text: str) -> Optional[datetime]:
    m = EPOCH_RE.search(text)
    if m:
        return datetime.fromtimestamp(int(m.group(1)))
    m = CLOCK_RE.search(text)
    if m:
        h, mi, ap = int(m.group(1)), int(m.group(2) or 0), (m.group(3) or "").lower()
        if ap == "pm" and h < 12:
            h += 12
        if ap == "am" and h == 12:
            h = 0
        now = datetime.now()
        t = now.replace(hour=h % 24, minute=mi, second=0, microsecond=0)
        if t <= now:
            t += timedelta(days=1)
        return t
    return None


def ask(prompt: str, *, model: str = "opus", cwd: Optional[Path] = None, allow_read: bool = False,
        on_wait: Optional[Callable[[Optional[datetime]], None]] = None, timeout: int = 900) -> str:
    """claude -p 로 한 번 묻고 결과 텍스트를 돌려준다. 한도면 기다렸다가 다시 묻는다."""
    exe = shutil.which("claude")
    if not exe:
        raise ClaudeError("claude CLI 가 없습니다. Claude Code 를 설치하고 `claude auth login` 하세요")
    cmd = [exe, "-p", "--output-format", "json", "--model", model]
    if allow_read:
        cmd += ["--allowedTools", "Read"]
    import os
    env = dict(os.environ, ANTHROPIC_API_KEY="", ANTHROPIC_AUTH_TOKEN="", ANTHROPIC_BASE_URL="")  # 구독(로그인)으로만
    waited_since = time.time()
    while True:
        try:
            proc = subprocess.run(cmd, input=prompt, capture_output=True, cwd=str(cwd) if cwd else None, env=env,
                                  timeout=timeout, encoding="utf-8", errors="replace",
                                  creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except subprocess.TimeoutExpired:
            log("  · Claude 응답 시간 초과 — 다시 시도")
            continue
        raw = (proc.stdout or "") + "\n" + (proc.stderr or "")
        result, is_error = "", proc.returncode != 0
        try:
            data = json.loads(proc.stdout)
            result = str(data.get("result") or "")
            is_error = is_error or bool(data.get("is_error"))
        except (json.JSONDecodeError, TypeError):
            result = proc.stdout or ""
        if not is_error and result.strip():
            if on_wait:
                on_wait(None)
            return result
        text = result + "\n" + raw
        if LIMIT_RE.search(text):
            if time.time() - waited_since > MAX_WAIT_HOURS * 3600:
                raise ClaudeError(f"Claude 한도가 {MAX_WAIT_HOURS}시간 넘게 풀리지 않았습니다")
            reset = _reset_at(text)
            now = datetime.now()
            if reset and reset > now:
                wake = min(reset + timedelta(seconds=90), now + timedelta(seconds=CHUNK_SEC))
                log(f"  ⏸ Claude 사용 한도 — {reset:%m월 %d일 %H:%M} 재설정 예정. {wake:%H:%M} 에 다시 확인합니다"
                    " (끝난 문항은 저장됨 · 창은 켜 두세요)")
            else:
                wake = now + timedelta(seconds=RETRY_SEC)
                log(f"  ⏸ Claude 사용 한도(또는 과부하) — {wake:%H:%M} 에 다시 확인합니다 (끝난 문항은 저장됨)")
            if on_wait:
                on_wait(wake)
            keep_awake(True)
            try:
                while datetime.now() < wake:
                    time.sleep(min(60, max(1, (wake - datetime.now()).total_seconds())))
            finally:
                keep_awake(False)
            log("  ▶ 다시 시도합니다")
            continue
        raise ClaudeError(f"Claude 호출 실패 (code {proc.returncode}): {text.strip()[:400]}")


def extract_json(text: str):
    """응답에서 JSON 객체를 꺼낸다 (```json 블록 또는 첫 { … 마지막 })."""
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    body = m.group(1) if m else text[text.find("{"): text.rfind("}") + 1]
    return json.loads(body)
