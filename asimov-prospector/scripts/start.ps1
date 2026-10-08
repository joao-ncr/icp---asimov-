$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
if (-not (Test-Path ".venv\Scripts\python.exe")) {
  Write-Host "Ambiente nao instalado. Execute scripts\bootstrap.ps1 primeiro."
  exit 1
}
& .\.venv\Scripts\python.exe run.py ui
