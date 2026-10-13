@echo off
rem Keep this batch file in CRLF for cmd.exe.
chcp 65001 >nul
cd /d "%~dp0"
set "CATALOG_PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%CATALOG_PYTHON%" set "CATALOG_PYTHON=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if exist "%CATALOG_PYTHON%" (
  "%CATALOG_PYTHON%" app.py --open
) else (
  python app.py --open
)
if errorlevel 1 (
  echo.
  echo Не удалось запустить каталог. Нужен Python 3.10 или новее.
  echo Если программа уже открыта, перейдите на http://127.0.0.1:8765
  pause
)
