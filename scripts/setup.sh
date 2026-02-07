#!/usr/bin/env bash
# MIGA Setup Script — Bootstrap the development environment
set -euo pipefail

BLUE='\033[0;34m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log()  { echo -e "${BLUE}[MIGA]${NC} $1"; }
ok()   { echo -e "${GREEN}  ✅ $1${NC}"; }
warn() { echo -e "${YELLOW}  ⚠️  $1${NC}"; }
err()  { echo -e "${RED}  ❌ $1${NC}"; }

log "Setting up MIGA development environment..."

# 1. Check prerequisites
log "Checking prerequisites..."

command -v python3 >/dev/null 2>&1 || { err "Python 3.11+ required"; exit 1; }
PYVER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
ok "Python $PYVER"

command -v docker >/dev/null 2>&1 && ok "Docker installed" || warn "Docker not found (needed for cluster)"
command -v docker compose version >/dev/null 2>&1 && ok "Docker Compose installed" || warn "Docker Compose not found"

# 2. Environment file
log "Setting up environment..."
if [ ! -f .env ]; then
    cp .env.example .env
    ok "Created .env from template"
    warn "Edit .env and add your API credentials before deploying"
else
    ok ".env already exists"
fi

# 3. Python virtual environment
log "Setting up Python environment..."
if [ ! -d .venv ]; then
    python3 -m venv .venv
    ok "Created virtual environment"
else
    ok "Virtual environment exists"
fi

source .venv/bin/activate

pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt
ok "Dependencies installed"

# 4. Install project in editable mode
pip install --quiet -e .
ok "MIGA shared library installed (editable)"

# 5. Linting check
log "Running lint check..."
if command -v ruff >/dev/null 2>&1; then
    ruff check . --quiet && ok "Lint passed" || warn "Lint warnings found"
else
    pip install --quiet ruff
    ruff check . --quiet && ok "Lint passed" || warn "Lint warnings found"
fi

# 6. Run tests
log "Running tests..."
pytest tests/ -q --tb=short 2>/dev/null && ok "Tests passed" || warn "Some tests need attention"

echo ""
log "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
log "Setup complete! Next steps:"
echo ""
echo "  1. Edit .env with your Cisco API credentials"
echo "  2. Start the cluster:  docker compose up -d"
echo "  3. Check status:       python -m packages.cli.miga_cli status"
echo "  4. Include stubs:      docker compose --profile stubs up -d"
echo ""
log "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
