#!/bin/bash
set -euo pipefail

BOLD="\033[1m"
GREEN="\033[0;32m"
RED="\033[0;31m"
DIM="\033[2m"
RESET="\033[0m"

info()  { echo -e "${BOLD}$*${RESET}"; }
ok()    { echo -e "${GREEN}✓${RESET} $*"; }
fail()  { echo -e "${RED}✗ $*${RESET}"; exit 1; }

echo ""
info "RawToWise Uninstaller"
echo ""

REMOVED=false

if command -v uv &>/dev/null && uv tool list 2>/dev/null | grep -q rawtowise; then
  info "Removing via uv..."
  uv tool uninstall rawtowise
  REMOVED=true
fi

if command -v pipx &>/dev/null && pipx list 2>/dev/null | grep -q rawtowise; then
  info "Removing via pipx..."
  pipx uninstall rawtowise
  REMOVED=true
fi

if pip show rawtowise &>/dev/null 2>&1; then
  info "Removing via pip..."
  pip uninstall -y rawtowise
  REMOVED=true
fi

if $REMOVED; then
  echo ""
  ok "RawToWise uninstalled"
else
  fail "RawToWise is not installed"
fi
