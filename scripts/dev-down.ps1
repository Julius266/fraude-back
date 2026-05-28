$ErrorActionPreference = "SilentlyContinue"

# Cierra procesos que esten escuchando en puertos de desarrollo del backend.
foreach ($p in @(8000, 8001, 8002)) {
    $listeners = Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue
    foreach ($listener in $listeners) {
        Stop-Process -Id $listener.OwningProcess -Force -ErrorAction SilentlyContinue
        Write-Host "Proceso detenido en puerto $p (PID $($listener.OwningProcess))."
    }
}

Write-Host "Backend detenido."
