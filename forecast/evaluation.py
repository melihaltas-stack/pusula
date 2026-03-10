"""
forecast/evaluation.py — Forecast Model Değerlendirme

Walk-forward validation ile tahmin modelinin performansını ölçer.

Metrikler:
    - Direction accuracy: Yön tahmin doğruluğu (hedef: > %55)
    - Hit rate by horizon: Her horizon için ayrı doğruluk
    - Overfit kontrolü: Train-test performans farkı < %10
"""

import logging
from typing import Optional

import pandas as pd
import numpy as np

from forecast.features import build_historical_features, FEATURE_COLUMNS
from forecast.forecast import find_similar_periods, HORIZONS, MIN_NEIGHBORS

logger = logging.getLogger("selvese.evaluation")


def evaluate_direction_accuracy(
    eur_df,
    dxy_df,
    vix_df,
    train_end_year: int = 2022,
) -> dict:
    """Walk-forward validation ile yön tahmin doğruluğunu ölçer.

    Train (< train_end_year): Benzer dönem havuzu
    Test  (>= train_end_year): Her gün için tahmin yap ve doğruluğu ölç

    Returns:
        {
            "horizons": {
                1: {"accuracy": float, "n_predictions": int, "baseline": 50.0},
                3: {...}, ...
            },
            "train_size": int,
            "test_size": int,
            "overfit_check": {"passed": bool, "train_avg": float, "test_avg": float, "gap": float},
            "overall_accuracy": float,
            "summary": str,
        }
    """
    hist_df = build_historical_features(eur_df, dxy_df, vix_df)

    if hist_df.empty or len(hist_df) < 200:
        return {
            "horizons": {},
            "train_size": 0, "test_size": 0,
            "overfit_check": {"passed": False, "train_avg": 0, "test_avg": 0, "gap": 0},
            "overall_accuracy": 0,
            "summary": "Değerlendirme için yeterli veri yok.",
        }

    # Split
    if hasattr(hist_df.index, 'year'):
        train_mask = hist_df.index.year <= train_end_year
    else:
        split_pt = int(len(hist_df) * 0.75)
        train_mask = pd.Series(False, index=hist_df.index)
        train_mask.iloc[:split_pt] = True

    train_df = hist_df[train_mask]
    test_df = hist_df[~train_mask]

    if len(train_df) < 100 or len(test_df) < 30:
        # Fallback: %70/%30
        split_pt = int(len(hist_df) * 0.70)
        train_df = hist_df.iloc[:split_pt]
        test_df = hist_df.iloc[split_pt:]

    available_cols = [c for c in FEATURE_COLUMNS if c in hist_df.columns]

    # ── Test set evaluation ──
    def _evaluate_set(reference_df, eval_df, label):
        results = {}
        for h in HORIZONS:
            dir_col = f"dir_{h}"
            if dir_col not in eval_df.columns:
                continue

            correct = 0
            total = 0

            # Her 5. gün örnekle (hesaplama süresini azalt)
            sample_indices = range(0, len(eval_df), 5)

            for i in sample_indices:
                row = eval_df.iloc[i]
                actual_dir = row.get(dir_col)
                if pd.isna(actual_dir):
                    continue

                # Bu günün feature'larını al
                row_features = {col: row.get(col) for col in available_cols}

                # Benzer dönemleri bul (sadece reference_df'ten)
                neighbors = find_similar_periods(row_features, reference_df)
                if len(neighbors) < MIN_NEIGHBORS:
                    continue

                # Tahmin: çoğunluk oyu
                pred_prob = neighbors[dir_col].mean() if dir_col in neighbors.columns else 0.5
                predicted_dir = 1.0 if pred_prob > 0.5 else 0.0

                if predicted_dir == actual_dir:
                    correct += 1
                total += 1

            if total > 0:
                accuracy = round((correct / total) * 100, 1)
            else:
                accuracy = 0.0

            results[h] = {
                "accuracy": accuracy,
                "n_predictions": total,
                "baseline": 50.0,
                "above_baseline": accuracy > 50.0,
            }

        return results

    # Train-on-train (overfit kontrolü)
    train_results = _evaluate_set(train_df, train_df, "train")
    # Train-on-test (gerçek performans)
    test_results = _evaluate_set(train_df, test_df, "test")

    # Overfit kontrolü
    train_accs = [v["accuracy"] for v in train_results.values() if v["n_predictions"] > 0]
    test_accs = [v["accuracy"] for v in test_results.values() if v["n_predictions"] > 0]

    train_avg = np.mean(train_accs) if train_accs else 0
    test_avg = np.mean(test_accs) if test_accs else 0
    gap = abs(train_avg - test_avg)

    overfit_check = {
        "passed": gap < 10,
        "train_avg": round(train_avg, 1),
        "test_avg": round(test_avg, 1),
        "gap": round(gap, 1),
    }

    # Genel doğruluk
    overall = round(test_avg, 1) if test_avg > 0 else 0

    # Özet
    parts = []
    for h in HORIZONS:
        if h in test_results and test_results[h]["n_predictions"] > 0:
            acc = test_results[h]["accuracy"]
            status = "✓" if acc > 52 else "≈" if acc > 48 else "✗"
            parts.append(f"{h}G: {status}%{acc:.0f}")

    summary = (
        f"Test accuracy: %{overall:.0f} | "
        f"Overfit gap: %{gap:.0f} {'(OK)' if gap < 10 else '(UYARI)'} | "
        + " | ".join(parts)
    )

    return {
        "horizons": test_results,
        "train_results": train_results,
        "train_size": len(train_df),
        "test_size": len(test_df),
        "overfit_check": overfit_check,
        "overall_accuracy": overall,
        "summary": summary,
    }
