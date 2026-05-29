param(
    [string]$EnvFile = ".env.despliegue",
    [switch]$Init,
    [string]$ProjectName = "fraude-back",
    [string]$ServiceName = "fraude-back",
    [switch]$SkipVariables
)

$ErrorActionPreference = "Stop"
Set-Location "$PSScriptRoot\.."

$env:Path = "C:\nvm4w\nodejs;C:\Users\luigg\AppData\Roaming\npm;" + $env:Path

if (-not (Get-Command railway -ErrorAction SilentlyContinue)) {
    throw "Railway CLI no instalado. Ejecuta: npm install -g @railway/cli"
}

function Test-RailwayHasService {
    $output = railway service list --json 2>$null
    if ($LASTEXITCODE -ne 0) { return $false }
    if ([string]::IsNullOrWhiteSpace($output)) { return $false }
    try {
        $services = $output | ConvertFrom-Json
        return ($services.Count -gt 0)
    } catch {
        return $false
    }
}

function Ensure-RailwayService {
    param([string]$Name)

    if (Test-RailwayHasService) {
        Write-Host "Servicio Railway existente detectado."
        railway service link $Name 2>$null | Out-Null
        return
    }

    Write-Host "No hay servicios. El primer 'railway up' creara el despliegue en '$Name'."
    railway service link $Name 2>$null | Out-Null
}

function Set-RailwayVariablesFromFile {
    param([string]$Path)

    Write-Host "Subiendo variables desde $Path..."
    Get-Content $Path -Encoding UTF8 | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#")) { return }
        if ($line -match "TU-SERVICIO|TU-FRONT") {
            Write-Host "  (omitida placeholder) $line"
            return
        }

        $eq = $line.IndexOf("=")
        if ($eq -lt 1) { return }

        $key = $line.Substring(0, $eq).Trim()
        $value = $line.Substring($eq + 1).Trim()
        if (-not $key) { return }

        Write-Host "  $key"
        railway variable set "${key}=${value}" --skip-deploys | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "Fallo al definir variable $key"
        }
    }
}

Write-Host "Comprobando sesion Railway..."
railway whoami
if ($LASTEXITCODE -ne 0) {
    throw @"
No hay sesion en Railway. En esta terminal ejecuta primero:

  railway login

O define RAILWAY_TOKEN con un token de https://railway.app/account/tokens
"@
}

if ($Init) {
    Write-Host "Creando proyecto '$ProjectName'..."
    railway init --name $ProjectName
}

Ensure-RailwayService -Name $ServiceName

if (-not (Test-Path $EnvFile)) {
    throw "No se encontro $EnvFile"
}

if (-not $SkipVariables) {
    Set-RailwayVariablesFromFile -Path $EnvFile
}

Write-Host ""
Write-Host "Desplegando (railway up)..."
railway up --detach --service $ServiceName
if ($LASTEXITCODE -ne 0) {
    throw "Fallo railway up"
}

Write-Host ""
Write-Host "Listo. Comandos utiles:"
Write-Host "  railway domain --service $ServiceName"
Write-Host "  railway logs --service $ServiceName"
Write-Host "  railway variable list --service $ServiceName"
Write-Host ""
Write-Host "Recuerda en el dashboard: Add Volume -> mount /data (token Gmail + adjuntos)"
