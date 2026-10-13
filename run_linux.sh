#!/usr/bin/env bash
set -euo pipefail
python3 -m pip install -r requirements.txt
python3 -m pip install sherlock-project==0.16.0
python3 run_local.py
