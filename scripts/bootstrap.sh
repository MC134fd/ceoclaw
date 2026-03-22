#!/usr/bin/env bash
# bootstrap.sh  –  CEOClaw one-time environment setup
#
# Creates a Python virtualenv if missing, installs dependencies, and
# initialises the SQLite database.
#
# Usage:
#   bash scripts/bootstrap.sh            # standard setup
#   PYTHON=python3.12 bash scripts/bootstrap.sh   # explicit interpreter
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_DIR"

PYTHON="${PYTHON:-python3}"
VENV_DIR=".venv"

_green() { printf '\033[32m%s\033[0m\n' "$*"; }
_bold()  { printf '\033[1m%s\033[0m\n'  "$*"; }
_info()  { printf '  %s\n' "$*"; }

_bold "── CEOClaw bootstrap ──"

# ---------------------------------------------------------------------------
# 1. Python version check
# ---------------------------------------------------------------------------
PY_VERSION=$("$PYTHON" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
_info "Python $PY_VERSION"

if ! "$PYTHON" -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)"; then
    printf '\033[31mError: Python >=3.11 required (found %s)\033[0m\n' "$PY_VERSION"
    exit 1
fi

# ---------------------------------------------------------------------------
# 2. Create virtualenv if missing
# ---------------------------------------------------------------------------
if [ ! -d "$VENV_DIR" ]; then
    _info "Creating virtualenv at $VENV_DIR"
    "$PYTHON" -m venv "$VENV_DIR"
fi

# Activate
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"
_info "Virtualenv: $VIRTUAL_ENV"

# ---------------------------------------------------------------------------
# 3. Install / upgrade dependencies
# ---------------------------------------------------------------------------
_bold "── Installing dependencies ──"
pip install -q --upgrade pip
pip install -q -r requirements.txt
_green "  Dependencies installed"

# ---------------------------------------------------------------------------
# 4. Create runtime directories
# ---------------------------------------------------------------------------
mkdir -p data/exports data/websites
_info "Runtime dirs: data/exports  data/websites"

# ---------------------------------------------------------------------------
# 5. Initialise SQLite database
# ---------------------------------------------------------------------------
_bold "── Initialising database ──"
python - <<'EOF'
from data.database import init_db
tables = init_db()
print(f"  Tables created: {len(tables)}  ({', '.join(tables[:4])}…)")
EOF
_green "  Database ready: data/ceoclaw.db"

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
echo
_bold "── Bootstrap complete ──"
_info "Activate:  source $VENV_DIR/bin/activate"
_info "Demo run:  python main.py demo --cycles 5"
_info "API:       uvicorn api.server:app --port 8000"
_info "Tests:     pytest -q"
echo
