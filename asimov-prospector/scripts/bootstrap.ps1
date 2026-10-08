$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
if (-not (Test-Path ".venv\Scripts\python.exe")) {
  py -3 -m venv .venv
}
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
if (-not (Test-Path ".env")) { Copy-Item .env.example .env }
& .\.venv\Scripts\python.exe run.py setup
& .\.venv\Scripts\python.exe -m pytest -q
Write-Host "`nPronto. Para iniciar a interface: .\.venv\Scripts\python.exe run.py ui"
