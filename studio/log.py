"""진행 로그: 콘솔과 작업별 로그 파일(대시보드가 실시간으로 읽는다)에 함께 쓴다."""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from typing import Optional

_lock = threading.Lock()
_file: Optional[Path] = None


def to_file(path: Optional[Path]) -> None:
    global _file
    _file = path
    if path:
        path.parent.mkdir(parents=True, exist_ok=True)


def log(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    with _lock:
        try:
            print(line, flush=True)
        except UnicodeEncodeError:
            sys.stdout.buffer.write((line + "\n").encode("utf-8", "replace"))
            sys.stdout.flush()
        if _file:
            with _file.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
