param(
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"

Set-Location "$PSScriptRoot\.."

if (-not (Test-Path ".\.venv\Scripts\python.exe")) {
    throw "No se encontro .venv. Ejecuta primero: python -m venv .venv y pip install -r requirements.txt"
}

# Mata cualquier proceso escuchando en los puertos de desarrollo comunes.
& "$PSScriptRoot\dev-down.ps1" | Out-Null

Write-Host "Aplicando migraciones de base de datos..."
& ".\.venv\Scripts\python.exe" -m alembic upgrade head
if ($LASTEXITCODE -ne 0) {
    throw "Fallo alembic upgrade head"
}

Write-Host ""
Write-Host "Iniciando backend en http://127.0.0.1:$Port ..."
Write-Host ""

& ".\.venv\Scripts\python.exe" -m uvicorn app.main:app --reload --host 127.0.0.1 --port $Port
