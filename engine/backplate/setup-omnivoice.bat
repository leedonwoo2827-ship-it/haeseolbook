@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
rem OmniVoice(보이스 클로닝 TTS) 설치 — NVIDIA GPU PC 전용. setup.bat 다음에 한 번.
rem   setup-omnivoice.bat <레퍼런스.wav> ["레퍼런스에서 말한 문장"]
rem GPU 없는 PC 는 이 파일을 건너뛰면 setup.bat 의 슈퍼토닉3(CPU)이 그대로 쓰인다.

if "%~1"=="" (
  echo 사용법: setup-omnivoice.bat ^<레퍼런스.wav^> ["레퍼런스 대사"]
  exit /b 2
)
where nvidia-smi >nul 2>&1
if errorlevel 1 (
  echo [omnivoice] NVIDIA GPU 가 없습니다 — 슈퍼토닉3^(CPU^)를 계속 쓰세요.
  exit /b 1
)

if not exist .venv-omnivoice\Scripts\python.exe (
  echo [omnivoice] 가상환경 생성 ^(.venv-omnivoice^)
  py -3.12 -m venv .venv-omnivoice 2>nul || python -m venv .venv-omnivoice || exit /b 1
)
.venv-omnivoice\Scripts\python -m pip install --upgrade pip
.venv-omnivoice\Scripts\python -m pip install torch==2.8.0+cu128 torchaudio==2.8.0+cu128 --extra-index-url https://download.pytorch.org/whl/cu128 || exit /b 1
.venv-omnivoice\Scripts\python -m pip install omnivoice soundfile pyyaml || exit /b 1
.venv-omnivoice\Scripts\python -c "import torch, omnivoice; assert torch.cuda.is_available(); print('[omnivoice] OK', torch.cuda.get_device_name(0))" || exit /b 1

.venv-app\Scripts\python tools\wire_tts.py omnivoice "%~dp0.venv-omnivoice\Scripts\python.exe" "%~1" "%~2" || exit /b 1
echo [omnivoice] 완료 — 되돌리려면 showcase.config.local.json 의 tts.engine 을 "supertonic3" 로.
