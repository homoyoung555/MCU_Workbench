@echo off
cd /d "%~dp0"
echo Starting WGL -^> Chroma3380P GUI ...
echo If an error appears below, send this window or startup_error.log (same folder).
echo.
where py >nul 2>nul
if %errorlevel%==0 (
    py "%~dp0gui.py"
) else (
    python "%~dp0gui.py"
)
echo.
echo ===== GUI exited =====
pause
