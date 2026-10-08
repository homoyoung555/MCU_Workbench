@echo off
setlocal
if exist "%~dp0toolchains\s100\S100\YT5100_Pre.exe" set "S100_HOME=%~dp0toolchains\s100"
if exist "%~dp0toolchains\chroma\craft\bin\plncmp.exe" set "CRAFT_HOME=%~dp0toolchains\chroma\craft"

cd /d "%~dp0"

if exist "%~dp0MCU_Workbench_App\MCU_Workbench_App.exe" (

  start "" "%~dp0MCU_Workbench_App\MCU_Workbench_App.exe"

) else (

  python "%~dp0gui\desktop.py"

  if errorlevel 1 pause

)

