#!/bin/sh
# Copyright (c) 2026 Stefan Koelle (https://stefankoelle.de)
# Licensed under the MIT License. See LICENSE file in project root for details.
set -e
REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
if [ -x "$REPO_ROOT/.venv/bin/python" ]; then
    PY="$REPO_ROOT/.venv/bin/python"
else
    PY="python3"
fi
cd "$REPO_ROOT"
export PYTHONDONTWRITEBYTECODE=1
exec "$PY" -m converter "$@"
