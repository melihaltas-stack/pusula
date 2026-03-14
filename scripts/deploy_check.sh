#!/usr/bin/env bash
set -euo pipefail

ROOT="/Users/melihaltas/Desktop/Pusula"
cd "$ROOT"

echo "[1/3] Python derleme kontrolu"
python3 -m py_compile app.py logger.py run.py \
  core/data_sources.py core/scoring.py core/validators.py \
  engine/engine.py planner/planner.py \
  forecast/forecast.py forecast/features.py forecast/evaluation.py forecast/calibration.py \
  backtest/backtest.py

echo "[2/3] Detail report script yardim cagrisi"
python3 scripts/generate_detail_report.py --help >/dev/null

echo "[3/3] Bilgi amacli smoke test notu"
echo "Smoke test komutu: python3 tests/smoke_check.py"
echo "Not: Dis veri saglayici rate-limit varsa uzun surebilir."

echo "OK: deploy check tamamlandi"
