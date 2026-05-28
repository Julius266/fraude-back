param(
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"

Set-Location "$PSScriptRoot\.."

if (-not (Test-Path ".\.venv\Scripts\python.exe")) {
    throw "No se encontro .venv. Ejecuta primero: python -m venv .venv y pip install -r requirements.txt"
}

# Mata cualquier proceso escuchando en los puertos de desarrollo comunes.
$portsToClear = @($Port, 8001, 8002)
foreach ($p in $portsToClear) {
    $listeners = Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue
    foreach ($listener in $listeners) {
        try {
            Stop-Process -Id $listener.OwningProcess -Force -ErrorAction SilentlyContinue
            Write-Host "Puerto $p liberado (PID $($listener.OwningProcess))."
        } catch {
            # Ignorar si el proceso ya no existe.
        }
    }
}

Write-Host ""
Write-Host "Iniciando backend en http://127.0.0.1:$Port ..."
Write-Host ""

& ".\.venv\Scripts\python.exe" -m uvicorn app.main:app --reload --host 127.0.0.1 --port $Port
