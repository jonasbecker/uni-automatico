#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

# Install dependencies if needed
pip install -q -r requirements.txt

# Launch GUI
python main.py
