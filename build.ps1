# build.ps1 — Package FullQA.ai Desktop as a standalone Windows .exe
# Run from the repo root:  .\build.ps1
# Output: dist\FullQA.ai.exe

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Write-Host "`n== FullQA.ai Desktop Builder ==" -ForegroundColor Cyan

# Activate venv
$activate = ".\.venv\Scripts\Activate.ps1"
if (-not (Test-Path $activate)) {
    Write-Error ".venv not found. Run:  uv venv .venv  then  uv pip install -r requirements.txt"
}
. $activate

# Install / upgrade build tools
Write-Host "`n-- Installing PyInstaller..." -ForegroundColor Yellow
pip install --quiet --upgrade pyinstaller

# Build
Write-Host "`n-- Building EXE (this may take 1-2 minutes)..." -ForegroundColor Yellow
pyinstaller `
    --onefile `
    --windowed `
    --name "FullQA.ai" `
    --add-data "desktop/ui.py;." `
    desktop/ui.py

if (Test-Path "dist\FullQA.ai.exe") {
    $size = [math]::Round((Get-Item "dist\FullQA.ai.exe").Length / 1MB, 1)
    Write-Host "`n✅ Build complete: dist\FullQA.ai.exe  ($size MB)" -ForegroundColor Green
    Write-Host "   Run it with:  .\dist\FullQA.ai.exe" -ForegroundColor Green
} else {
    Write-Error "Build failed — dist\FullQA.ai.exe not found."
}
