$ErrorActionPreference = "SilentlyContinue"

Set-Location "$PSScriptRoot\.."

# 1. Matar procesos escuchando en puertos de desarrollo.
foreach ($p in @(8000, 8001, 8002)) {
    for ($attempt = 0; $attempt -lt 3; $attempt++) {
        $listeners = Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue
        if (-not $listeners) { break }

        foreach ($listener in $listeners) {
            $processId = $listener.OwningProcess
            Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
            Write-Host "Proceso detenido en puerto $p (PID $processId)."
        }
        Start-Sleep -Milliseconds 500
    }
}

# 2. Matar procesos Python/uvicorn huérfanos del proyecto (Windows Store python incluido).
Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object {
        $_.CommandLine -and (
            $_.CommandLine -like "*uvicorn*app.main*" -or
            $_.CommandLine -like "*fraude-back*uvicorn*"
        )
    } |
    ForEach-Object {
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        Write-Host "Uvicorn detenido (PID $($_.ProcessId))."
    }

Write-Host "Backend detenido."
