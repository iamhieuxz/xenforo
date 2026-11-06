@echo off
REM Mo Coc Coc o cong debug 9222 voi profile THAT (co san phien dang nhap),
REM roi mo app.
REM
REM Dieu kien: phai dong het Coc Coc truoc. Chromium chi doc co
REM --remote-debugging-port luc khoi dong, va giu khoa doc quyen tren file
REM Cookies cua profile dang mo.

setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    set PY=.venv\Scripts\python.exe
) else (
    set PY=python
)

echo ==========================================================
echo  BUOC 1: Mo Coc Coc o cong debug 9222
echo ==========================================================
echo.
"%PY%" open_debug_chrome.py
if errorlevel 1 (
    echo.
    echo [!] Khong mo duoc cong debug.
    echo     Hay dong HET cua so Coc Coc roi chay lai file nay.
    pause
    exit /b 1
)

echo.
echo ==========================================================
echo  BUOC 2: Mo app
echo ==========================================================
echo.
"%PY%" gui_fluent.py

endlocal