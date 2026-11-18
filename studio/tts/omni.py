"""OmniVoice TTS 엔진(기본) — 스튜디오 venv 에는 torch 가 없다. OmniVoice 폴더의 venv python 으로
상주 워커(omni_worker.py)를 한 번 띄워 두고 문장마다 보낸다(모델은 프로세스당 한 번 적재).

설정: _assets/tts.json (이 PC 에만 — 레포에 올리지 않음)
    {"engine": "omnivoice",                       ← "supertonic3" 로 바꾸면 옛 엔진
     "omnivoice": {"python": "D:/…/261118-OmniVoice/.venv/Scripts/python.exe",
                   "ref_audio": "D:/…/261118-OmniVoice/voice_01.wav", "ref_text": "", "steps": 32}}
목소리는 레퍼런스 wav 하나(W1). 작업의 voice 칸은 캐시 이름에만 쓰인다.
"""
from __future__ import annotations

import atexit
import json
import subprocess
import tempfile
import threading
import time
import wave
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "_assets" / "tts.json"
WORKER = Path(__file__).with_name("omni_worker.py")
LOG = ROOT / "logs" / "omnivoice-worker.log"
DEFAULT_HOME = Path(r"D:\00work\261118-OmniVoice")
SR = 24000
MAX_CHARS = 200          # 이보다 긴 줄은 문장·쉼표에서 잘라 합성(OmniVoice 권장 길이)
PIECE_GAP = 0.12
IDLE_SEC = 300           # 이만큼 합성이 없으면 워커를 내린다(다음 합성 때 다시 올림 ≈20초)
TAG = "@@OMNI "


def config() -> Dict[str, Any]:
    try:
        cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    except Exception:
        cfg = {}
    o = dict(cfg.get("omnivoice") or {})
    o.setdefault("python", str(DEFAULT_HOME / ".venv" / "Scripts" / "python.exe"))
    o.setdefault("ref_audio", str(DEFAULT_HOME / "voice_01.wav"))
    o.setdefault("ref_text", "")
    o.setdefault("steps", 32)
    return {"engine": cfg.get("engine", "omnivoice"), "omnivoice": o}


def missing() -> List[str]:
    o = config()["omnivoice"]
    return [f"{k}: {o[k]}" for k in ("python", "ref_audio") if not Path(o[k]).is_file()]


def _read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32767.0


def _trim(x: np.ndarray, sr: int) -> np.ndarray:
    """앞뒤 무음을 진폭으로 잘라낸다(앞 0.03s · 뒤 0.15s 남김) — 문장 사이 무음은 voice.py 가 따로 넣는다"""
    nz = np.where(np.abs(x) > 0.01)[0]
    if len(nz) == 0:
        return x
    a = max(0, int(nz[0]) - int(sr * 0.03))
    b = min(len(x), int(nz[-1]) + int(sr * 0.15))
    return x[a:b]


class OmniEngine:
    _instance: Optional["OmniEngine"] = None
    name = "omnivoice"

    def __init__(self) -> None:
        miss = missing()
        if miss:
            raise RuntimeError("OmniVoice 가 준비되지 않았습니다 — " + " · ".join(miss) + f" (설정 {CONFIG})")
        self.cfg = config()["omnivoice"]
        self.sample_rate = SR
        self._lock = threading.Lock()
        self._p: Optional[subprocess.Popen] = None
        self._tmp = Path(tempfile.mkdtemp(prefix="omni-"))
        self.stats = {"lines": 0, "sec_audio": 0.0, "sec_synth": 0.0}
        self._last = time.time()
        atexit.register(self.close)
        # 오래 쉬면 워커를 내려 GPU 메모리를 비운다 — 대시보드(음성 체크 한 줄 합성)가 체인 생산과 GPU 를 오래 나눠 쓰지 않게
        threading.Thread(target=self._idle_watch, daemon=True).start()

    def _idle_watch(self) -> None:
        while True:
            time.sleep(30)
            if self._p is not None and time.time() - self._last > IDLE_SEC and self._lock.acquire(blocking=False):
                try:
                    self.close()
                finally:
                    self._lock.release()

    @classmethod
    def get(cls) -> "OmniEngine":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _start(self) -> None:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        err = open(LOG, "a", encoding="utf-8", errors="replace")
        self._p = subprocess.Popen(
            [self.cfg["python"], "-I", "-u", str(WORKER), self.cfg["ref_audio"], self.cfg.get("ref_text") or ""],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=err,
            encoding="utf-8", errors="replace", bufsize=1,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        r = self._reply()
        if not r.get("ready"):
            self.close()
            raise RuntimeError(f"OmniVoice 워커를 띄우지 못했습니다: {r.get('error')}  (로그 {LOG})")

    def _reply(self) -> Dict[str, Any]:
        assert self._p and self._p.stdout
        while True:
            line = self._p.stdout.readline()
            if not line:
                return {"ok": False, "error": f"워커가 끝났습니다 (로그 {LOG})"}
            if line.startswith(TAG):
                return json.loads(line[len(TAG):])

    def _one(self, text: str, speed: float) -> np.ndarray:
        if self._p is None or self._p.poll() is not None:
            self._start()
        out = self._tmp / "line.wav"
        assert self._p and self._p.stdin
        self._p.stdin.write(json.dumps({"text": text, "speed": speed, "steps": int(self.cfg.get("steps") or 32),
                                        "out": str(out)}, ensure_ascii=False) + "\n")
        self._p.stdin.flush()
        r = self._reply()
        if not r.get("ok"):
            raise RuntimeError(f"OmniVoice 합성 실패: {r.get('error')}")
        return _trim(_read_wav(out), SR)

    def synth(self, text: str, *, voice: str = "W1", speed: float = 1.0, lang: str = "ko",
              subject: Optional[str] = None, raw: bool = False) -> np.ndarray:
        from .engine import _split_for_tts, spoken
        if not raw:
            text = spoken(text, subject)
        pieces = _split_for_tts(text, MAX_CHARS)
        if not pieces:
            return np.zeros(0, dtype=np.float32)
        t0 = time.time()
        gap = np.zeros(int(SR * PIECE_GAP), dtype=np.float32)
        parts: List[np.ndarray] = []
        with self._lock:
            for i, piece in enumerate(pieces):
                parts.append(self._one(piece, speed))
                if i < len(pieces) - 1:
                    parts.append(gap)
        wav = np.concatenate(parts).astype(np.float32)
        self._last = time.time()
        self.stats["lines"] += 1
        self.stats["sec_audio"] += len(wav) / SR
        self.stats["sec_synth"] += time.time() - t0
        return wav

    def close(self) -> None:
        p, self._p = self._p, None
        if p and p.poll() is None:
            try:
                p.stdin.write(json.dumps({"quit": True}) + "\n")
                p.stdin.flush()
                p.wait(timeout=10)
            except Exception:
                p.kill()
