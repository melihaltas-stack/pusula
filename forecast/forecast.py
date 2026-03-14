"""
forecast/forecast.py — İstatistiksel Yön Tahmin Motoru

"EUR/USD 5 gün sonra nereye gider?" sorusuna istatistiksel cevap üretir.

Model: Nearest-neighbor + weighted voting.
Neden ML regression değil?
- Yfinance verisi ile scikit-learn'ün kurulu olma garantisi yok.
- Basit ama istatistiksel olarak doğrulanmış bir model,
  karmaşık ama doğrulanmamış modelden daha iyidir.

Yaklaşım:
    1. Mevcut feature vektörünü hesapla
    2. Tarihsel veriden benzer feature vektörlerini bul
    3. Benzer günlerin ileri dönem getirisinden olasılık çıkar
    4. Güven aralığı ekle
"""

import logging
from typing import Optional

import pandas as pd
import numpy as np

from forecast.features import (
    build_feature_row, build_historical_features,
    FEATURE_COLUMNS, TARGET_COLUMNS, DIRECTION_COLUMNS,
)
from backtest.confidence import wilson_interval

logger = logging.getLogger("selvese.forecast")

# Horizonlar
HORIZONS = [1, 3, 5, 10]

# Benzerlik eşikleri
MAX_NEIGHBORS = 80
MIN_NEIGHBORS = 15
SIMILARITY_PERCENTILE = 15  # en yakın %15


def _normalize_features(df: pd.DataFrame, columns: list) -> pd.DataFrame:
    """Feature'ları 0-1 arasına normalize eder (min-max)."""
    result = df.copy()
    for col in columns:
        if col not in result.columns:
            continue
        series = result[col]
        lo, hi = series.min(), series.max()
        if hi - lo > 1e-10:
            result[col] = (series - lo) / (hi - lo)
        else:
            result[col] = 0.5
    return result


def _euclidean_distance(row_a: dict, df_b: pd.DataFrame, columns: list) -> pd.Series:
    """Tek bir satır ile DataFrame'deki tüm satırlar arası Euclidean mesafe."""
    distances = pd.Series(0.0, index=df_b.index)
    valid_cols = 0

    for col in columns:
        if col not in df_b.columns:
            continue
        val_a = row_a.get(col)
        if val_a is None or pd.isna(val_a):
            continue

        col_b = df_b[col]
        mask = col_b.notna()
        distances[mask] += (col_b[mask] - val_a) ** 2
        valid_cols += 1

    if valid_cols == 0:
        return distances

    return np.sqrt(distances / valid_cols)


def find_similar_periods(
    current_features: dict,
    historical_df: pd.DataFrame,
    n_neighbors: int = MAX_NEIGHBORS,
) -> pd.DataFrame:
    """Mevcut koşullara en benzer tarihsel dönemleri bulur.

    Args:
        current_features: build_feature_row() çıktısı (normalize edilmiş)
        historical_df: build_historical_features() çıktısı
        n_neighbors: Döndürülecek maksimum benzer dönem

    Returns:
        En yakın n komşuyu içeren DataFrame (hedef kolonlarıyla).
    """
    if historical_df.empty or len(historical_df) < MIN_NEIGHBORS:
        return pd.DataFrame()

    # Normalize
    available_cols = [c for c in FEATURE_COLUMNS if c in historical_df.columns]
    if not available_cols:
        return pd.DataFrame()

    norm_df = _normalize_features(historical_df, available_cols)

    # Current features'ı da normalize et (aynı min-max ile)
    norm_current = {}
    for col in available_cols:
        if col not in historical_df.columns:
            continue
        val = current_features.get(col)
        if val is None:
            norm_current[col] = None
            continue
        lo, hi = historical_df[col].min(), historical_df[col].max()
        if hi - lo > 1e-10:
            norm_current[col] = (val - lo) / (hi - lo)
        else:
            norm_current[col] = 0.5

    # Mesafe hesapla
    distances = _euclidean_distance(norm_current, norm_df, available_cols)

    # En yakın n komşu
    n = min(n_neighbors, int(len(distances) * SIMILARITY_PERCENTILE / 100))
    n = max(MIN_NEIGHBORS, n)
    n = min(n, len(distances))

    nearest_idx = distances.nsmallest(n).index

    return historical_df.loc[nearest_idx].copy()


def forecast_direction(
    eur_df,
    dxy_df=None,
    vix_df=None,
    us2y=None,
    de2y=None,
    spread_2y_history=None,
    spx_df=None,
    eurostoxx_df=None,
    gold_df=None,
    oil_df=None,
    cross_asset=None,
    cot_positioning=None,
    market_regime: str = "RANGE",
) -> dict:
    """Ana tahmin fonksiyonu.

    Args:
        eur_df, dxy_df, vix_df: OHLC DataFrames
        us2y, de2y: Faiz oranları
        market_regime: Mevcut piyasa rejimi

    Returns:
        {
            "horizons": {
                1: {"direction": "DOWN", "probability": 58.0, "ci_lower": ..., "ci_upper": ..., "avg_return": ..., "reliable": bool},
                3: {...}, 5: {...}, 10: {...},
            },
            "sample_size": int,
            "model_type": str,
            "summary": str,
            "current_features": dict,
        }
    """
    # Feature'ları hesapla
    current = build_feature_row(
        eur_df,
        dxy_df,
        vix_df,
        us2y,
        de2y,
        spread_2y_history=spread_2y_history,
        cross_asset=cross_asset,
        cot_positioning=cot_positioning,
        market_regime=market_regime,
    )

    # Tarihsel feature matrix
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

    if hist_df.empty or len(hist_df) < MIN_NEIGHBORS:
        return {
            "horizons": {},
            "sample_size": 0,
            "model_type": "nearest_neighbor",
            "summary": "Tahmin için yeterli tarihsel veri yok.",
            "current_features": current,
        }

    # Benzer dönemleri bul
    neighbors = find_similar_periods(current, hist_df)

    if len(neighbors) < MIN_NEIGHBORS:
        return {
            "horizons": {},
            "sample_size": len(neighbors),
            "model_type": "nearest_neighbor",
            "summary": f"Yeterli benzer dönem bulunamadı (n={len(neighbors)}).",
            "current_features": current,
        }

    # Her horizon için tahmin
    horizons = {}
    for h in HORIZONS:
        dir_col = f"dir_{h}"
        ret_col = f"ret_{h}"

        if dir_col not in neighbors.columns or ret_col not in neighbors.columns:
            continue

        valid = neighbors[[dir_col, ret_col]].dropna()
        if len(valid) < 5:
            continue

        # Yön olasılığı (dir=1 → EUR düştü = satış doğru)
        down_count = int(valid[dir_col].sum())
        total = len(valid)
        ci = wilson_interval(down_count, total)

        # Ortalama getiri
        avg_ret = float(valid[ret_col].mean())
        median_ret = float(valid[ret_col].median())

        # Yön
        direction = "DOWN" if ci["point"] > 50 else "UP" if ci["point"] < 50 else "NEUTRAL"

        horizons[h] = {
            "direction": direction,
            "probability": ci["point"],
            "ci_lower": ci["lower"],
            "ci_upper": ci["upper"],
            "avg_return": round(avg_ret, 3),
            "median_return": round(median_ret, 3),
            "sample_size": total,
            "reliable": ci["reliable"],
        }

    # Özet
    summary_parts = []
    for h in HORIZONS:
        if h in horizons:
            hd = horizons[h]
            prob_text = f"%{hd['probability']:.0f}"
            ci_text = f"(CI: %{hd['ci_lower']:.0f}\u2013%{hd['ci_upper']:.0f})"
            direction_emoji = "\u2193" if hd["direction"] == "DOWN" else "\u2191" if hd["direction"] == "UP" else "\u2194"
            summary_parts.append(f"{h}G: {direction_emoji}{prob_text} {ci_text}")

    summary = f"n={len(neighbors)} | " + " | ".join(summary_parts) if summary_parts else "Tahmin üretilemedi."

    return {
        "horizons": horizons,
        "sample_size": len(neighbors),
        "model_type": "nearest_neighbor",
        "summary": summary,
        "current_features": {k: round(v, 4) if isinstance(v, float) else v for k, v in current.items()},
    }
