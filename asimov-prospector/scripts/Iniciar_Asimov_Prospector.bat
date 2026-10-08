@echo off
setlocal
cd /d "%~dp0.."
if not exist ".venv\Scripts\python.exe" (
  echo Primeira inicializacao. Isso pode levar alguns minutos...
  powershell -ExecutionPolicy Bypass -File "scripts\bootstrap.ps1"
  if errorlevel 1 (
    echo.
    echo Nao foi possivel preparar o ambiente.
    pause
    exit /b 1
  )
)
call ".venv\Scripts\python.exe" run.py ui
pause
