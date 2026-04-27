# launch.ps1 — Build dashboard from current Excel + open in default browser.
#
# Usage:
#   - Right-click → "Run with PowerShell"
#   - OR from terminal: powershell -ExecutionPolicy Bypass -File scripts\launch.ps1

$ErrorActionPreference = "Stop"
$env:PYTHONIOENCODING = "utf-8"

# Refresh PATH from registry (in case nvm/uv installed in a previous session)
$env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")

# Resolve repo root from script location
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

Write-Host ""
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host " Application de suivi budgetaire — local launcher" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host ""

# Check uvx availability
$uvx = Get-Command uvx -ErrorAction SilentlyContinue
if (-not $uvx) {
    Write-Host "ERREUR: uvx n'est pas dans le PATH." -ForegroundColor Red
    Write-Host "  Installe via: winget install astral-sh.uv" -ForegroundColor Yellow
    Read-Host "Appuie sur Entree pour fermer"
    exit 1
}

Write-Host "Etape 1/2: Generation du dashboard (parsers VN + SAV + CPT EXPL)..." -ForegroundColor Yellow
$buildScript = Join-Path $repoRoot "scripts\build-local-dashboard.py"
if (-not (Test-Path $buildScript)) {
    Write-Host "ERREUR: $buildScript introuvable." -ForegroundColor Red
    Read-Host "Appuie sur Entree pour fermer"
    exit 1
}

uvx --with openpyxl python "$buildScript"
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "ERREUR: la generation du dashboard a echoue (code $LASTEXITCODE)." -ForegroundColor Red
    Read-Host "Appuie sur Entree pour fermer"
    exit 1
}

$dashboardPath = Join-Path $repoRoot "scripts\.local\dashboard.html"
if (-not (Test-Path $dashboardPath)) {
    Write-Host ""
    Write-Host "ERREUR: $dashboardPath n'a pas ete genere." -ForegroundColor Red
    Read-Host "Appuie sur Entree pour fermer"
    exit 1
}

$sizeKB = [math]::Round((Get-Item $dashboardPath).Length / 1KB, 1)
Write-Host ""
Write-Host "Etape 2/2: Ouverture dans le navigateur ($sizeKB KB)..." -ForegroundColor Yellow
Start-Process $dashboardPath

Write-Host ""
Write-Host "OK. Le dashboard est ouvert." -ForegroundColor Green
Write-Host "  Fichier: $dashboardPath" -ForegroundColor Gray
Write-Host ""
Write-Host "(Tu peux fermer cette fenetre.)"
Start-Sleep -Seconds 3
