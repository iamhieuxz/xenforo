@echo off
REM Mo Chrome o cong debug 9222 voi profile co san phien dang nhap.
REM Bam dup file nay la duoc.

setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    set PY=.venv\Scripts\python.exe
) else (
    set PY=python
)

"%PY%" open_debug_chrome.py %*

echo.
pause