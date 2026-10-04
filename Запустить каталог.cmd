@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "BUNDLED_PYTHON=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if exist "%BUNDLED_PYTHON%" (
  "%BUNDLED_PYTHON%" app.py --open
) else (
  python app.py --open
)
if errorlevel 1 (
  echo.
  echo Не удалось запустить каталог. Нужен Python 3.10 или новее.
  echo Если программа уже открыта, перейдите на http://127.0.0.1:8765
  pause
)
