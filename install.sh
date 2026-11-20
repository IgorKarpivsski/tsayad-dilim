#!/usr/bin/env bash
# Local setup (Linux/macOS/WSL). On Windows without WSL: install Python 3.12 + FFmpeg, then run the same pip command.
set -euo pipefail
cd "$(dirname "$0")"
python3 -m venv .venv
. .venv/bin/activate
pip install -U pip
pip install -r requirements.txt pytest
command -v ffmpeg >/dev/null || echo "⚠️  FFmpeg not found – videos will be skipped locally (CI installs it automatically)."
[ -f .env ] || cp .env.example .env
python -m tsayad keygen
echo "✅ Installed. Paste the generated DATA_KEY / TRACKER_SECRET into .env and your GitHub Secrets, then run: python -m pytest -q && python -m tsayad check"
