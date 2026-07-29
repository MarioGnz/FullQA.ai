#!/usr/bin/env bash
# install.sh — macOS / Linux setup script
# Run from the project root: bash install.sh

set -e

echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║           FullQA.ai — Setup (macOS/Linux)        ║"
echo "╚══════════════════════════════════════════════════╝"
echo ""

# ── Python virtual environment ───────────────────────────────────
if [ ! -d ".venv" ]; then
  echo "[1/4] Creating Python virtual environment…"
  python3 -m venv .venv
else
  echo "[1/4] Virtual environment already exists — skipping."
fi

source .venv/bin/activate

echo "[2/4] Installing host-agent dependencies…"
pip install --upgrade pip -q
pip install -r requirements.txt -q
echo "      Done."

# ── .env file ────────────────────────────────────────────────────
if [ ! -f ".env" ]; then
  echo "[3/4] Creating .env from template…"
  cp .env.example .env
  echo "      ⚠  Edit .env and set your ANTHROPIC_API_KEY before running."
else
  echo "[3/4] .env already exists — skipping."
fi

# Restrict permissions
chmod 600 .env

# ── Pre-commit hook ───────────────────────────────────────────────
if [ -d ".git" ]; then
  echo "[4/4] Installing pre-commit hook…"
  cp hooks/pre-commit .git/hooks/pre-commit
  chmod +x .git/hooks/pre-commit
  echo "      Done."
else
  echo "[4/4] No .git directory — skipping pre-commit hook."
fi

echo ""
echo "✅ Setup complete!"
echo ""
echo "Next steps:"
echo "  1. Add your Anthropic API key to .env"
echo "  2. Start the Docker backend:  docker compose up -d"
echo "  3. Run the host agent:        python agent/main.py"
echo "  4. Open the web UI:           http://localhost:3000"
echo ""
