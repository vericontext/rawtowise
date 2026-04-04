#!/bin/bash
set -euo pipefail

REPO="https://github.com/vericontext/rawtowise.git"
MIN_PYTHON="3.11"
BOLD="\033[1m"
GREEN="\033[0;32m"
RED="\033[0;31m"
DIM="\033[2m"
RESET="\033[0m"

info()  { echo -e "${BOLD}$*${RESET}"; }
ok()    { echo -e "${GREEN}✓${RESET} $*"; }
fail()  { echo -e "${RED}✗ $*${RESET}"; exit 1; }
dim()   { echo -e "${DIM}$*${RESET}"; }

# ── Python check ──────────────────────────────────────────────
find_python() {
  for cmd in python3 python; do
    if command -v "$cmd" &>/dev/null; then
      local ver
      ver=$("$cmd" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
      if "$cmd" -c "import sys; exit(0 if sys.version_info >= (3,11) else 1)" 2>/dev/null; then
        PYTHON="$cmd"
        PYTHON_VER="$ver"
        return 0
      fi
    fi
  done
  return 1
}

# ── Main ──────────────────────────────────────────────────────
echo ""
info "RawToWise Installer"
dim  "LLM Knowledge Compiler"
echo ""

# 1. Python
if find_python; then
  ok "Python $PYTHON_VER found ($PYTHON)"
else
  fail "Python >= $MIN_PYTHON is required. Install it from https://python.org"
fi

# 2. Choose install method: pipx > uv > pip
if command -v pipx &>/dev/null; then
  INSTALLER="pipx"
  INSTALL_CMD="pipx install git+${REPO}"
  UPGRADE_CMD="pipx upgrade rawtowise"
elif command -v uv &>/dev/null; then
  INSTALLER="uv"
  INSTALL_CMD="uv tool install git+${REPO}"
  UPGRADE_CMD="uv tool upgrade rawtowise"
else
  INSTALLER="pip"
  INSTALL_CMD="$PYTHON -m pip install --user git+${REPO}"
  UPGRADE_CMD="$PYTHON -m pip install --user --upgrade git+${REPO}"
fi

ok "Using $INSTALLER"

# 3. Check if already installed → upgrade
if command -v rtw &>/dev/null; then
  info "Existing installation found, upgrading..."
  eval "$UPGRADE_CMD"
else
  info "Installing RawToWise..."
  eval "$INSTALL_CMD"
fi

# 4. Verify
if command -v rtw &>/dev/null; then
  echo ""
  ok "Installed $(rtw version 2>&1)"
  echo ""
  info "Get started:"
  echo "  export ANTHROPIC_API_KEY=\"sk-...\""
  echo "  rtw init --name \"My Research\""
  echo "  rtw ingest https://example.com/article"
  echo "  rtw compile"
  echo "  rtw query \"What are the key insights?\""
  echo ""
else
  echo ""
  fail "Installation completed but 'rtw' not found in PATH.
  If you used pip, add ~/.local/bin to your PATH:
    export PATH=\"\$HOME/.local/bin:\$PATH\""
fi
