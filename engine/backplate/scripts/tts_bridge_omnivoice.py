# -*- coding: utf-8 -*-
"""TTS 브리지 (OmniVoice) — `tts_bridge.py` 와 **같은 파일 계약**으로 도는 두 번째 엔진.

    콘솔  →  job.json   {"items":[{"no":5,"text":"…"}], "ref_audio":"…wav", …}
             ↓  OmniVoice venv(torch+CUDA) 의 python 으로 실행
    콘솔  ←  result.json {"items":[{"no":5,"file":"005.wav","sec":4.1}], "sample_rate":24000}

    python tts_bridge_omnivoice.py <job.json> <result.json>

★ **목소리는 프리셋 코드(F2)가 아니라 레퍼런스 wav 다.** `tts.ref_audio` 의
  3~10초 음성을 복제한다. `tts.ref_text` 를 비우면 Whisper 가 받아쓴다.
  받아쓰기·인코딩 결과는 레퍼런스 해시로 캐시해서(`~/.cache/omnivoice-cli/`,
  omnivoice-cli 와 공유) 한 장 다시 합성할 때 Whisper 를 다시 띄우지 않는다.

★ **발음사전은 슈퍼토닉과 같은 것을 쓴다** — `tts/pronunciation.py`·`tts/tags.py`
  는 yaml 만 의존해서 onnxruntime 없이 import 된다. 엔진을 바꿨다고 `/dict` 에서
  고친 발음이 안 먹으면 안 된다.

★ 슈퍼토닉의 `speed`·`total_step(8)` 은 뜻이 다르다. speed 는 그대로 넘기고,
  스텝은 `tts.num_step`(기본 32) 을 쓴다.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import traceback
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
SR = 24000
CACHE = Path(os.environ.get("OMNIVOICE_CLI_CACHE", Path.home() / ".cache" / "omnivoice-cli"))


def _prompt_file(ref: Path, ref_text: str | None) -> Path:
    """.pt 를 직접 줬으면 그것, 아니면 레퍼런스 해시 캐시 자리(omnivoice-cli 와 같은 규칙)."""
    if ref.suffix.lower() == ".pt":
        return ref
    h = hashlib.sha1(ref.read_bytes())
    h.update((ref_text or "").encode("utf-8"))
    return CACHE / f"{ref.stem}_{h.hexdigest()[:12]}.pt"


def _prompt(model, ref: Path, ref_text: str | None):
    from omnivoice import VoiceClonePrompt

    cached = _prompt_file(ref, ref_text)
    if cached.is_file():
        return VoiceClonePrompt.load(str(cached))
    p = model.create_voice_clone_prompt(ref_audio=str(ref), ref_text=ref_text or None)
    CACHE.mkdir(parents=True, exist_ok=True)
    p.save(str(cached))
    return p


def main() -> int:
    if len(sys.argv) < 3:
        print("usage: tts_bridge_omnivoice.py <job.json> <result.json>", file=sys.stderr)
        return 2
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    job_path, out_path = Path(sys.argv[1]), Path(sys.argv[2])
    job = json.loads(job_path.read_text(encoding="utf-8"))
    if str(APP) not in sys.path:
        sys.path.insert(0, str(APP))

    result = {"items": [], "sample_rate": SR, "error": None}
    try:
        import soundfile as sf
        import torch
        from omnivoice import OmniVoice
        from tts.pronunciation import load_pronunciation_map

        ref = Path(job.get("ref_audio") or "")
        if not ref.is_file():
            raise FileNotFoundError(f"레퍼런스 음성이 없습니다(tts.ref_audio): {ref}")
        ref_text = (job.get("ref_text") or "").strip() or None
        speed = float(job.get("speed") or 1.0)
        steps = int(job.get("num_step") or 32)
        pmap = load_pronunciation_map(APP / "tts" / "config" / "pronunciation_map.yaml")

        out_dir = Path(job["out_dir"])
        out_dir.mkdir(parents=True, exist_ok=True)

        if not torch.cuda.is_available():
            raise RuntimeError("CUDA GPU 가 없습니다 — OmniVoice 는 NVIDIA GPU 가 필요합니다 "
                               "(GPU 없는 PC 는 tts.engine 을 supertonic3 로)")
        need_asr = not ref_text and not _prompt_file(ref, ref_text).is_file()
        model = OmniVoice.from_pretrained("k2-fsa/OmniVoice", device_map="cuda:0",
                                          dtype=torch.float16, load_asr=need_asr)
        prompt = _prompt(model, ref, ref_text)

        for it in job["items"]:
            no = int(it["no"])
            text = (it.get("text") or "").strip()
            if not text:
                continue
            name = f"{no:03d}.wav"
            try:
                spoken = pmap.apply(text, spell_unknown_acronyms=True, convert_years=True)
                wav = model.generate(text=spoken, voice_clone_prompt=prompt,
                                     speed=speed, num_step=steps)[0]
            except Exception as e:  # noqa: BLE001
                result["items"].append({"no": no, "error": f"{type(e).__name__}: {e}"})
                print(f"[{no}] 실패 {e}", flush=True)
                continue
            sf.write(str(out_dir / name), wav, SR, subtype="PCM_16")
            sec = round(len(wav) / float(SR), 2)
            result["items"].append({"no": no, "file": name, "sec": sec})
            print(f"[{no}] {sec:.1f}s {name}", flush=True)
    except Exception:  # noqa: BLE001
        result["error"] = traceback.format_exc(limit=6)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return 1 if result["error"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
