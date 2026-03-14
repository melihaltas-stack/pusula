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

from forecast.calibration import summarize_calibration
from forecast.features import build_historical_features, FEATURE_COLUMNS
from forecast.forecast import find_similar_periods, HORIZONS, MIN_NEIGHBORS

logger = logging.getLogger("selvese.evaluation")

MODEL_LABELS = {
    "rule_based": "Kural",
    "forecast": "Forecast",
    "hybrid": "Hybrid",
}


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _split_train_test(hist_df: pd.DataFrame, train_end_year: int):
    if hasattr(hist_df.index, "year"):
        train_mask = hist_df.index.year <= train_end_year
    else:
        split_pt = int(len(hist_df) * 0.75)
        train_mask = pd.Series(False, index=hist_df.index)
        train_mask.iloc[:split_pt] = True

    train_df = hist_df[train_mask]
    test_df = hist_df[~train_mask]

    if len(train_df) < 100 or len(test_df) < 30:
        split_pt = int(len(hist_df) * 0.70)
        train_df = hist_df.iloc[:split_pt]
        test_df = hist_df.iloc[split_pt:]

    return train_df, test_df


def _rule_probability(row: pd.Series, horizon: int) -> float:
    prob = 50.0

    dxy_ret_3 = row.get("dxy_ret_3")
    mom_5 = row.get("mom_5")
    mom_20 = row.get("mom_20")
    ma_dist = row.get("ma20_ma50_dist")
    vix_norm = row.get("vix_norm")
    atr_pct = row.get("atr_pct")
    spread_mom = row.get("spread_2y_mom_5")
    gold_ret = row.get("gold_ret_5")
    equity_rel = row.get("equity_rel_5")

    if pd.notna(dxy_ret_3):
        prob += _clamp(float(dxy_ret_3) * 4.0, -12.0, 12.0)
    if pd.notna(mom_5):
        prob += _clamp(float(-mom_5) * 2.0, -14.0, 14.0)
    if pd.notna(ma_dist):
        prob += _clamp(float(-ma_dist) * 12.0, -10.0, 10.0)
    if pd.notna(vix_norm):
        prob += _clamp((float(vix_norm) - 0.36) * 40.0, -8.0, 8.0)
    if pd.notna(atr_pct):
        prob += _clamp((float(atr_pct) - 0.65) * 12.0, -5.0, 5.0)
    if pd.notna(spread_mom):
        prob += _clamp(float(-spread_mom) * 0.9, -7.0, 7.0)
    if pd.notna(gold_ret):
        prob += _clamp(float(gold_ret) * 0.6, -5.0, 5.0)
    if pd.notna(equity_rel):
        prob += _clamp(float(-equity_rel) * 0.7, -5.0, 5.0)

    if horizon >= 5 and pd.notna(mom_20):
        prob += _clamp(float(-mom_20) * 1.1, -10.0, 10.0)

    return round(_clamp(prob, 0.0, 100.0), 1)


def _hybrid_probability(rule_prob: float, forecast_prob: float, sample_size: int) -> float:
    sample_factor = min(max(sample_size, 0) / 40.0, 1.0)
    forecast_weight = 0.45 + 0.25 * sample_factor
    rule_weight = 1.0 - forecast_weight
    return round((rule_prob * rule_weight) + (forecast_prob * forecast_weight), 1)


def _evaluate_models(reference_df: pd.DataFrame, eval_df: pd.DataFrame, available_cols: list) -> dict:
    model_hits = {
        "rule_based": {h: {"correct": 0, "total": 0} for h in HORIZONS},
        "forecast": {h: {"correct": 0, "total": 0} for h in HORIZONS},
        "hybrid": {h: {"correct": 0, "total": 0} for h in HORIZONS},
    }
    model_probs = {
        "rule_based": [],
        "forecast": [],
        "hybrid": [],
    }

    sample_indices = range(0, len(eval_df), 5)

    for i in sample_indices:
        row = eval_df.iloc[i]
        row_features = {col: row.get(col) for col in available_cols}
        neighbors = find_similar_periods(row_features, reference_df)

        for h in HORIZONS:
            dir_col = f"dir_{h}"
            if dir_col not in eval_df.columns:
                continue

            actual_dir = row.get(dir_col)
            if pd.isna(actual_dir):
                continue

            rule_prob = _rule_probability(row, h)
            rule_pred = 1.0 if rule_prob > 50 else 0.0
            model_hits["rule_based"][h]["correct"] += int(rule_pred == actual_dir)
            model_hits["rule_based"][h]["total"] += 1
            model_probs["rule_based"].append((rule_prob, actual_dir))

            if len(neighbors) < MIN_NEIGHBORS or dir_col not in neighbors.columns:
                continue

            forecast_prob = float(neighbors[dir_col].mean() * 100)
            forecast_pred = 1.0 if forecast_prob > 50 else 0.0
            model_hits["forecast"][h]["correct"] += int(forecast_pred == actual_dir)
            model_hits["forecast"][h]["total"] += 1
            model_probs["forecast"].append((forecast_prob, actual_dir))

            hybrid_prob = _hybrid_probability(rule_prob, forecast_prob, len(neighbors))
            hybrid_pred = 1.0 if hybrid_prob > 50 else 0.0
            model_hits["hybrid"][h]["correct"] += int(hybrid_pred == actual_dir)
            model_hits["hybrid"][h]["total"] += 1
            model_probs["hybrid"].append((hybrid_prob, actual_dir))

    results = {}
    for model_name, horizon_map in model_hits.items():
        horizons = {}
        accuracies = []
        for h, counters in horizon_map.items():
            total = counters["total"]
            accuracy = round((counters["correct"] / total) * 100, 1) if total else 0.0
            horizons[h] = {
                "accuracy": accuracy,
                "n_predictions": total,
                "baseline": 50.0,
                "above_baseline": accuracy > 50.0,
            }
            if total > 0:
                accuracies.append(accuracy)

        results[model_name] = {
            "horizons": horizons,
            "overall_accuracy": round(float(np.mean(accuracies)), 1) if accuracies else 0.0,
            "calibration": summarize_calibration(
                [prob for prob, _ in model_probs[model_name]],
                [outcome for _, outcome in model_probs[model_name]],
            ),
        }

    return results


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

    train_df, test_df = _split_train_test(hist_df, train_end_year)

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


def evaluate_hybrid_performance(
    eur_df,
    dxy_df,
    vix_df,
    spread_2y_history=None,
    spx_df=None,
    eurostoxx_df=None,
    gold_df=None,
    oil_df=None,
    train_end_year: int = 2022,
) -> dict:
    hist_df = build_historical_features(
        eur_df,
        dxy_df,
        vix_df,
        spread_2y_history=spread_2y_history,
        spx_df=spx_df,
        eurostoxx_df=eurostoxx_df,
        gold_df=gold_df,
        oil_df=oil_df,
    )

    if hist_df.empty or len(hist_df) < 200:
        return {
            "models": {},
            "train_size": 0,
            "test_size": 0,
            "best_model": None,
            "summary": "Hibrit performans raporu için yeterli veri yok.",
        }

    train_df, test_df = _split_train_test(hist_df, train_end_year)
    available_cols = [c for c in FEATURE_COLUMNS if c in hist_df.columns]
    models = _evaluate_models(train_df, test_df, available_cols)

    ranked = sorted(
        ((name, model["overall_accuracy"]) for name, model in models.items()),
        key=lambda item: item[1],
        reverse=True,
    )
    best_model = ranked[0][0] if ranked else None
    hybrid_acc = models.get("hybrid", {}).get("overall_accuracy", 0.0)
    forecast_acc = models.get("forecast", {}).get("overall_accuracy", 0.0)
    rule_acc = models.get("rule_based", {}).get("overall_accuracy", 0.0)

    best_label = MODEL_LABELS.get(best_model, best_model or "N/A")
    summary = (
        f"En iyi model: {best_label} | "
        f"Hybrid %{hybrid_acc:.0f} | Forecast %{forecast_acc:.0f} | "
        f"Kural %{rule_acc:.0f} | "
        f"Hybrid lift vs Forecast: {hybrid_acc - forecast_acc:+.1f} puan | "
        f"Hybrid lift vs Kural: {hybrid_acc - rule_acc:+.1f} puan"
    )

    return {
        "models": models,
        "train_size": len(train_df),
        "test_size": len(test_df),
        "best_model": best_model,
        "summary": summary,
    }
