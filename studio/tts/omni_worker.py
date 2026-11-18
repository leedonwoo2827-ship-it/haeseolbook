# -*- coding: utf-8 -*-
"""OmniVoice 상주 워커 — 스튜디오가 OmniVoice venv(torch+CUDA)의 python 으로 한 번 띄워 둔다.

    python omni_worker.py <ref_audio> [ref_text]

모델은 처음 한 번만 올리고(≈16초) 그다음부터는 한 줄씩 받는다.
    stdin  {"text": "…", "speed": 1.0, "steps": 32, "out": "C:/…/x.wav"}
    stdout @@OMNI {"ok": true, "sec": 3.21}      (다른 줄은 라이브러리 로그 — 부르는 쪽이 무시)

발음 변환은 하지 않는다 — 스튜디오(engine.spoken)가 사전을 다 거친 글을 보낸다.
음성 프롬프트 캐시는 백플레이트 브리지·omnivoice-cli 와 같은 자리·같은 이름(~/.cache/omnivoice-cli).
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import traceback
from pathlib import Path

SR = 24000
CACHE = Path(os.environ.get("OMNIVOICE_CLI_CACHE", Path.home() / ".cache" / "omnivoice-cli"))
TAG = "@@OMNI "


def _prompt_file(ref: Path, ref_text: str | None) -> Path:
    if ref.suffix.lower() == ".pt":
        return ref
    h = hashlib.sha1(ref.read_bytes())
    h.update((ref_text or "").encode("utf-8"))
    return CACHE / f"{ref.stem}_{h.hexdigest()[:12]}.pt"


def _say(obj) -> None:
    sys.stdout.write(TAG + json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main() -> int:
    for s in (sys.stdout, sys.stdin):
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8")
    ref = Path(sys.argv[1])
    ref_text = (sys.argv[2] if len(sys.argv) > 2 else "").strip() or None
    try:
        import soundfile as sf
        import torch
        from omnivoice import OmniVoice, VoiceClonePrompt
        if not ref.is_file():
            raise FileNotFoundError(f"레퍼런스 음성이 없습니다: {ref}")
        if torch.cuda.is_available():
            dev, dtype = "cuda:0", torch.float16
        else:
            dev, dtype = "cpu", torch.float32
        cached = _prompt_file(ref, ref_text)
        model = OmniVoice.from_pretrained("k2-fsa/OmniVoice", device_map=dev, dtype=dtype,
                                          load_asr=not ref_text and not cached.is_file())
        if cached.is_file():
            prompt = VoiceClonePrompt.load(str(cached))
        else:
            prompt = model.create_voice_clone_prompt(ref_audio=str(ref), ref_text=ref_text)
            CACHE.mkdir(parents=True, exist_ok=True)
            prompt.save(str(cached))
    except Exception:  # noqa: BLE001
        _say({"ok": False, "fatal": True, "error": traceback.format_exc(limit=6)})
        return 1
    _say({"ok": True, "ready": True, "device": dev, "sample_rate": SR})

    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            req = json.loads(raw)
            if req.get("quit"):
                break
            wav = model.generate(text=req["text"], voice_clone_prompt=prompt,
                                 speed=float(req.get("speed") or 1.0), num_step=int(req.get("steps") or 32))[0]
            out = Path(req["out"])
            out.parent.mkdir(parents=True, exist_ok=True)
            sf.write(str(out), wav, SR, subtype="PCM_16")
            _say({"ok": True, "sec": round(len(wav) / float(SR), 3)})
        except Exception as e:  # noqa: BLE001
            _say({"ok": False, "error": f"{type(e).__name__}: {e}"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
