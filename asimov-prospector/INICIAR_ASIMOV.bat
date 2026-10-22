@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Preparando o Asimov Prospector pela primeira vez...
  py -3 -m venv .venv
  if errorlevel 1 goto erro
  .venv\Scripts\python.exe -m pip install --upgrade pip
  if errorlevel 1 goto erro
  .venv\Scripts\python.exe -m pip install -r requirements.txt
  if errorlevel 1 goto erro
  if not exist ".env" copy ".env.example" ".env" >nul
  .venv\Scripts\python.exe run.py setup
  if errorlevel 1 goto erro
)
echo Abrindo o Asimov Prospector no navegador...
.venv\Scripts\python.exe -m streamlit run app\ui\streamlit_app.py
if errorlevel 1 goto erro
goto fim
:erro
echo.
echo Nao foi possivel iniciar. Verifique se o Python 3.11 ou superior esta instalado.
pause
:fim
endlocal
