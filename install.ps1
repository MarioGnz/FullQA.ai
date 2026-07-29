# install.ps1 — Windows setup script
# Run from the project root in PowerShell: .\install.ps1

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "╔══════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║         FullQA.ai — Setup (Windows)              ║" -ForegroundColor Cyan
Write-Host "╚══════════════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""

# ── Python virtual environment ────────────────────────────────────
if (-Not (Test-Path ".venv")) {
    Write-Host "[1/4] Creating Python virtual environment…"
    python -m venv .venv
} else {
    Write-Host "[1/4] Virtual environment already exists — skipping."
}

& .\.venv\Scripts\Activate.ps1

Write-Host "[2/4] Installing host-agent dependencies…"
pip install --upgrade pip -q
pip install -r requirements.txt -q
Write-Host "      Done."

# ── .env file ─────────────────────────────────────────────────────
if (-Not (Test-Path ".env")) {
    Write-Host "[3/4] Creating .env from template…"
    Copy-Item .env.example .env
    Write-Host "      ⚠  Edit .env and set your ANTHROPIC_API_KEY before running." -ForegroundColor Yellow
} else {
    Write-Host "[3/4] .env already exists — skipping."
}

# ── Pre-commit hook ───────────────────────────────────────────────
if (Test-Path ".git") {
    Write-Host "[4/4] Installing pre-commit hook…"
    if (-Not (Test-Path ".git\hooks")) { New-Item -ItemType Directory ".git\hooks" | Out-Null }
    Copy-Item hooks\pre-commit .git\hooks\pre-commit -Force
    Write-Host "      Done. (Hook runs if you use Git Bash or WSL)"
} else {
    Write-Host "[4/4] No .git directory — skipping pre-commit hook."
}

Write-Host ""
Write-Host "✅ Setup complete!" -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:"
Write-Host "  1. Add your Anthropic API key to .env"
Write-Host "  2. Start the Docker backend:  docker compose up -d"
Write-Host "  3. Run the host agent:        python agent\main.py"
Write-Host "  4. Open the web UI:           http://localhost:3000"
Write-Host ""
