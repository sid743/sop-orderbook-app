@echo off
REM S&OP Order Book - start the app (first start creates .venv and installs packages)
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Creating Python environment...
  python -m venv .venv || goto :nopython
  ".venv\Scripts\python.exe" -m pip install --upgrade pip
  ".venv\Scripts\python.exe" -m pip install -r backend\requirements.txt || goto :fail
)
echo Starting on http://127.0.0.1:8000  (close this window to stop)
start "" http://127.0.0.1:8000
".venv\Scripts\python.exe" -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
goto :eof
:nopython
echo Python was not found. Install Python 3.10+ from python.org and tick "Add python.exe to PATH".
pause
goto :eof
:fail
echo Package install failed. Check the internet/proxy connection and run this file again.
pause
