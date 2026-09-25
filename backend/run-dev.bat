@echo off
REM Activate the project venv and start the API (Windows).
cd /d "%~dp0"
if not exist ".venv\Scripts\activate.bat" (
  echo Creating .venv ...
  python -m venv .venv
  call .venv\Scripts\activate.bat
  python -m pip install -U pip
  pip install -e ".[ingestion]" google-auth PyJWT
) else (
  call .venv\Scripts\activate.bat
)
uvicorn app.main:app --reload --port 8000
