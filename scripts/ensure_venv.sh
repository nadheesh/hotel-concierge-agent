#!/usr/bin/env bash
# Make sure the shared project virtualenv exists, optionally install
# requirements into it, then export VENV_PY pointing at its interpreter.
#
#   source scripts/ensure_venv.sh                       # venv only, install nothing
#   source scripts/ensure_venv.sh agent mcp/hotel-mcp   # venv + those requirements
#
# One venv at the repo root serves every component, so the Python version is the
# same everywhere. Components ask for what they actually need: the console needs
# no third-party packages, so it asks for none rather than dragging in the
# agent's model stack.
#
# Installs are stamped per requirement-set against a hash of the files, so
# repeated runs are a no-op and asking for a different set does not cause the
# other one to reinstall. Delete .venv/.deps-stamp-* to force a reinstall.

set -euo pipefail

_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
_VENV="$_ROOT/.venv"

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 not found on PATH. Install Python 3.11 or newer and retry." >&2
  exit 1
fi

_pyver=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')
case "$_pyver" in
  3.1[1-9]|3.[2-9]*) : ;;
  *) echo "Python $_pyver found; this project needs 3.11 or newer." >&2; exit 1 ;;
esac

if [ ! -x "$_VENV/bin/python" ]; then
  echo "Creating virtualenv at .venv (Python $_pyver) ..."
  python3 -m venv "$_VENV"
  rm -f "$_VENV"/.deps-stamp-*
fi

VENV_PY="$_VENV/bin/python"
export VENV_PY

# No components requested: the venv itself was all that was needed.
if [ "$#" -eq 0 ]; then
  return 0 2>/dev/null || exit 0
fi

_reqs=()
for _c in "$@"; do
  _r="$_ROOT/$_c/requirements.txt"
  [ -f "$_r" ] && _reqs+=("$_r")
done
if [ "${#_reqs[@]}" -eq 0 ]; then
  return 0 2>/dev/null || exit 0
fi

# Stamp name is derived from which components were asked for, so `agent` and
# `web` requests never invalidate each other.
_key=$(printf '%s\n' "$@" | shasum -a 256 | cut -d' ' -f1 | cut -c1-12)
_stamp="$_VENV/.deps-stamp-$_key"
_want=$(cat "${_reqs[@]}" | shasum -a 256 | cut -d' ' -f1)
_have=$(cat "$_stamp" 2>/dev/null || true)

if [ "$_want" != "$_have" ]; then
  echo "Installing dependencies for: $* (a minute the first time) ..."
  "$VENV_PY" -m pip install --quiet --upgrade pip
  for _r in "${_reqs[@]}"; do
    echo "  $(basename "$(dirname "$_r")")/requirements.txt"
    "$VENV_PY" -m pip install --quiet -r "$_r"
  done
  echo "$_want" > "$_stamp"
  echo "Dependencies ready."
fi
