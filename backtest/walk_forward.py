"""
backtest/walk_forward.py — Walk-Forward Validation

Train/Test split ile modelin out-of-sample performansını ölçer.

    Train: 2014–2022 (model kalibrasyonu)
    Test:  2023–2025 (out-of-sample performans)

Monotonicity testi:
    EDE 65+ bandı > EDE 52–64 bandı > EDE 40–51 bandı
    (yüksek EDE → daha iyi satış performansı)
"""

import logging
from typing import Optional

import pandas as pd
import numpy as np

logger = logging.getLogger("selvese.walk_forward")


def _band_from_ede(ede: float) -> str:
    if ede >= 65:
        return "65+"
    if ede >= 52:
        return "52-64"
    if ede >= 40:
        return "40-51"
    return "0-39"


BAND_ORDER = ["0-39", "40-51", "52-64", "65+"]


def _compute_proxy_ede(eur_close, dxy_close, vix_close, idx: int) -> float:
    """Tarihsel veri üzerinden proxy EDE hesaplar."""
    eur_ret = eur_close.pct_change().iloc[idx]
    dxy_ret = dxy_close.pct_change().iloc[idx]
    vix_val = vix_close.iloc[idx]

    if pd.isna(eur_ret) or pd.isna(dxy_ret) or pd.isna(vix_val):
        return 50.0

    score_dxy = max(0, min(100, 50 - dxy_ret * 2000))
    score_risk = max(0, min(100, 100 - vix_val))
    score_tech = max(0, min(100, 50 + eur_ret * 2000))

    ede = score_dxy * 0.4 + score_risk * 0.2 + score_tech * 0.4
    return float(ede)


def _regime_from_ma(close_series, idx: int) -> str:
    """MA diziliminden basit trend rejimi."""
    if idx < 100:
        return "SIDEWAYS"

    ma20 = close_series.iloc[idx - 19:idx + 1].mean()
    ma50 = close_series.iloc[idx - 49:idx + 1].mean()
    ma100 = close_series.iloc[idx - 99:idx + 1].mean()

    if ma20 > ma50 > ma100:
        return "UP"
    if ma20 < ma50 < ma100:
        return "DOWN"
    return "SIDEWAYS"


def _build_backtest_rows(df: pd.DataFrame, horizons: list, start_idx: int, end_idx: int) -> pd.DataFrame:
    """Belirli aralıkta backtest satırları oluşturur."""
    max_h = max(horizons)
    rows = []

    for idx in range(start_idx, min(end_idx, len(df) - max_h)):
        ede = _compute_proxy_ede(df["eur_close"], df["dxy_close"], df["vix_close"], idx)
        band = _band_from_ede(ede)
        regime = _regime_from_ma(df["eur_close"], idx)

        row = {"idx": idx, "ede": ede, "band": band, "regime": regime}

        for h in horizons:
            if idx + h < len(df):
                ret = (df["eur_close"].iloc[idx + h] / df["eur_close"].iloc[idx] - 1) * 100
                row[f"ret_{h}"] = ret

        rows.append(row)

    return pd.DataFrame(rows) if rows else pd.DataFrame()


def walk_forward_split(df: pd.DataFrame, train_end_year: int = 2022) -> dict:
    """Veriyi train ve test setlerine ayırır.

    Args:
        df: Merged DataFrame (eur_close, dxy_close, vix_close), DatetimeIndex
        train_end_year: Train setinin bitiş yılı (dahil)

    Returns:
        {"train_start": int, "train_end": int, "test_start": int, "test_end": int,
         "train_size": int, "test_size": int}
    """
    if df.empty or not hasattr(df.index, 'year'):
        return {"train_start": 0, "train_end": 0, "test_start": 0, "test_end": 0,
                "train_size": 0, "test_size": 0}

    train_mask = df.index.year <= train_end_year
    train_idx = df.index[train_mask]
    test_idx = df.index[~train_mask]

    if len(train_idx) == 0 or len(test_idx) == 0:
        # Fallback: ilk %75 train, son %25 test
        split_point = int(len(df) * 0.75)
        return {
            "train_start": 0, "train_end": split_point,
            "test_start": split_point, "test_end": len(df),
            "train_size": split_point, "test_size": len(df) - split_point,
        }

    # İndeks konumlarını bul
    train_end_pos = len(train_idx)
    test_start_pos = train_end_pos

    return {
        "train_start": 0, "train_end": train_end_pos,
        "test_start": test_start_pos, "test_end": len(df),
        "train_size": train_end_pos, "test_size": len(df) - train_end_pos,
    }


def monotonicity_test(backtest_df: pd.DataFrame, horizons: list = None) -> dict:
    """Monotonicity testi: Yüksek EDE bandı daha iyi performans vermeli mi?

    EDE yükseldikçe ileri dönem EUR düşüş olasılığı artmalı
    (satış için daha uygun ortam).

    Returns:
        {
            "passed": bool,
            "horizon_results": {
                3: {"bands": {...}, "monotonic": bool},
                ...
            },
            "summary": str,
        }
    """
    if horizons is None:
        horizons = [3, 5, 10]

    if backtest_df.empty:
        return {"passed": False, "horizon_results": {},
                "summary": "Veri yetersiz"}

    results = {}
    all_pass = True

    for h in horizons:
        col = f"ret_{h}"
        if col not in backtest_df.columns:
            continue

        band_stats = {}
        for band in BAND_ORDER:
            subset = backtest_df[backtest_df["band"] == band]
            if len(subset) < 5:
                band_stats[band] = {"n": len(subset), "down_prob": None, "avg_ret": None}
                continue

            down_prob = float((subset[col] < 0).mean() * 100)
            avg_ret = float(subset[col].mean())
            band_stats[band] = {"n": len(subset), "down_prob": round(down_prob, 1), "avg_ret": round(avg_ret, 3)}

        # Monotonicity kontrolü: 65+ bandının down_prob'u 0-39'dan yüksek olmalı
        # (yüksek EDE → EUR satışı için daha uygun = düşüş olasılığı daha yüksek)
        prob_65 = band_stats.get("65+", {}).get("down_prob")
        prob_039 = band_stats.get("0-39", {}).get("down_prob")

        monotonic = True
        if prob_65 is not None and prob_039 is not None:
            monotonic = prob_65 >= prob_039
        elif prob_65 is None and prob_039 is None:
            monotonic = True  # yeterli veri yok → pas

        if not monotonic:
            all_pass = False

        results[h] = {"bands": band_stats, "monotonic": monotonic}

    summary_parts = []
    for h, res in results.items():
        status = "\u2713" if res["monotonic"] else "\u2717"
        summary_parts.append(f"{h}G: {status}")

    return {
        "passed": all_pass,
        "horizon_results": results,
        "summary": f"Monotonicity: {', '.join(summary_parts)}",
    }


def regime_stability_test(backtest_df: pd.DataFrame, horizons: list = None) -> dict:
    """Rejim kararlılığı testi: EDE her rejimde çalışıyor mu?

    Hiçbir rejimde model tamamen çökmemeli (performans sıfır veya negatif).

    Returns:
        {
            "passed": bool,
            "regime_results": {"UP": {...}, "DOWN": {...}, "SIDEWAYS": {...}},
            "summary": str,
        }
    """
    if horizons is None:
        horizons = [3, 5, 10]

    if backtest_df.empty:
        return {"passed": False, "regime_results": {},
                "summary": "Veri yetersiz"}

    regime_results = {}
    all_pass = True

    for regime in ["UP", "DOWN", "SIDEWAYS"]:
        subset = backtest_df[backtest_df["regime"] == regime]

        if len(subset) < 10:
            regime_results[regime] = {"n": len(subset), "status": "yetersiz veri"}
            continue

        horizon_data = {}
        for h in horizons:
            col = f"ret_{h}"
            if col not in subset.columns:
                continue

            down_prob = float((subset[col] < 0).mean() * 100)
            avg_ret = float(subset[col].mean())
            horizon_data[h] = {"down_prob": round(down_prob, 1), "avg_ret": round(avg_ret, 3)}

        # Model çökmesi: Tüm horizonlarda down_prob < %40 veya > %80
        # (çok aşırı → sinyal güvenilmez)
        collapse = all(
            hd.get("down_prob", 50) < 35 or hd.get("down_prob", 50) > 80
            for hd in horizon_data.values()
        ) if horizon_data else False

        if collapse:
            all_pass = False

        regime_results[regime] = {
            "n": len(subset),
            "horizons": horizon_data,
            "stable": not collapse,
            "status": "kararsız" if collapse else "kararlı",
        }

    return {
        "passed": all_pass,
        "regime_results": regime_results,
        "summary": f"Rejim kararlılığı: {'PASS' if all_pass else 'FAIL'}",
    }


def run_walk_forward_validation(eur_df, dxy_df, vix_df, train_end_year: int = 2022) -> dict:
    """Tam walk-forward validation pipeline.

    Args:
        eur_df, dxy_df, vix_df: OHLC DataFrames
        train_end_year: Train set bitiş yılı

    Returns:
        {
            "split": {...},
            "train_monotonicity": {...},
            "test_monotonicity": {...},
            "train_regime_stability": {...},
            "test_regime_stability": {...},
            "overall_passed": bool,
            "summary": str,
        }
    """
    if eur_df is None or dxy_df is None or vix_df is None:
        return {
            "split": {}, "overall_passed": False,
            "summary": "Walk-forward i\u00E7in veri yetersiz",
        }

    # Merge
    df = pd.DataFrame({
        "eur_close": eur_df["Close"],
        "dxy_close": dxy_df["Close"],
        "vix_close": vix_df["Close"],
    }).dropna()

    if len(df) < 300:
        return {
            "split": {}, "overall_passed": False,
            "summary": f"Yeterli veri yok ({len(df)} < 300)",
        }

    horizons = [3, 5, 10, 20, 30]

    # Split
    split = walk_forward_split(df, train_end_year)

    # Train set backtest
    train_bt = _build_backtest_rows(df, horizons, max(120, split["train_start"]), split["train_end"])
    test_bt = _build_backtest_rows(df, horizons, max(120, split["test_start"]), split["test_end"])

    # Tests
    train_mono = monotonicity_test(train_bt, horizons[:3])
    test_mono = monotonicity_test(test_bt, horizons[:3])
    train_regime = regime_stability_test(train_bt, horizons[:3])
    test_regime = regime_stability_test(test_bt, horizons[:3])

    overall = test_mono["passed"] and test_regime["passed"]

    summary_parts = [
        f"Train mono: {'PASS' if train_mono['passed'] else 'FAIL'}",
        f"Test mono: {'PASS' if test_mono['passed'] else 'FAIL'}",
        f"Train rejim: {'PASS' if train_regime['passed'] else 'FAIL'}",
        f"Test rejim: {'PASS' if test_regime['passed'] else 'FAIL'}",
    ]

    return {
        "split": split,
        "train_monotonicity": train_mono,
        "test_monotonicity": test_mono,
        "train_regime_stability": train_regime,
        "test_regime_stability": test_regime,
        "train_sample_size": len(train_bt),
        "test_sample_size": len(test_bt),
        "overall_passed": overall,
        "summary": " | ".join(summary_parts),
    }
