#!/usr/bin/env bash
set -e
cd "$(dirname "$0")/.."
export LD_LIBRARY_PATH="/home/runner/.nix-profile/lib:$LD_LIBRARY_PATH"
export PIP_USER=0
.venv/bin/pytest "$@"
