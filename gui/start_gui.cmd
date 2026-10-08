@echo off
chcp 65001 >nul
set "MCU_GUI_PYTHON=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if not exist "%MCU_GUI_PYTHON%" (
  echo 未找到本机已配置的Python运行环境，请联系维护者。
  pause
  exit /b 1
)
"%MCU_GUI_PYTHON%" -B "%~dp0launch.py" %*
if errorlevel 1 pause
