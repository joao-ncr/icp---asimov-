#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
[ -f .env ] || cp .env.example .env
python run.py setup
python -m pytest -q
echo "Pronto. Para iniciar a interface: .venv/bin/python run.py ui"
