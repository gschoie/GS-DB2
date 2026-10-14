@echo off
chcp 65001 >nul
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo Python이 설치되어 있지 않습니다. https://www.python.org/downloads/ 에서 설치 후 다시 실행하세요.
    pause
    exit /b 1
)

if not exist ".venv" (
    echo 첫 실행: 가상환경 생성 및 패키지 설치 중...
    python -m venv .venv
    .venv\Scripts\pip install -r requirements.txt
)

.venv\Scripts\python longshot.py --ocr %*
pause
