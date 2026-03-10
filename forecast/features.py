"""
forecast/features.py — Feature Engineering

EUR/USD yön tahmini için kullanılan özellik seti.

Kategoriler:
    Teknik    : RSI, MACD histogram, MA20/MA50 mesafesi, ATR
    Makro     : DXY 3G/5G değişim, VIX seviyesi, US-DE 2Y spread
    Rejim     : Mevcut rejim (one-hot encoded)
    Seasonality: Ay, hafta günü
    Momentum  : 5G ve 20G getiri
"""

import logging
from typing import Optional

import pandas as pd
import numpy as np

from core.indicators import (
    safe_float, sma, rsi, macd_hist, atr, momentum_pct, clamp,
)

logger = logging.getLogger("selvese.features")


def _safe_pct_change(series, periods=1):
    """NaN-safe yüzde değişim."""
    if series is None or len(series) < periods + 1:
        return None
    start = safe_float(series.iloc[-(periods + 1)])
    end = safe_float(series.iloc[-1])
    if start is None or end is None or start == 0:
        return None
    return (end / start - 1) * 100


def build_feature_row(
    eur_df,
    dxy_df=None,
    vix_df=None,
    us2y: Optional[float] = None,
    de2y: Optional[float] = None,
    market_regime: str = "RANGE",
) -> dict:
    """Tek bir zaman dilimi için özellik vektörü oluşturur.

    Args:
        eur_df: EUR/USD OHLC DataFrame
        dxy_df: DXY OHLC DataFrame
        vix_df: VIX OHLC DataFrame
        us2y: ABD 2Y faiz
        de2y: Almanya 2Y faiz
        market_regime: Mevcut piyasa rejimi

    Returns:
        {"feature_name": value, ...}  — tüm özellikler float veya None
    """
    features = {}

    # ── Teknik özellikler ──
    if eur_df is not None and not eur_df.empty and len(eur_df) >= 50:
        close = eur_df["Close"]

        # RSI
        rsi_val = safe_float(rsi(close).iloc[-1]) if len(close) >= 15 else None
        features["rsi_14"] = rsi_val

        # RSI normalize (0-1)
        features["rsi_norm"] = rsi_val / 100 if rsi_val is not None else None

        # MACD histogram
        mh = safe_float(macd_hist(close).iloc[-1]) if len(close) >= 35 else None
        features["macd_hist"] = mh

        # MACD histogram normalize (fiyata göre)
        last_close = safe_float(close.iloc[-1])
        if mh is not None and last_close and last_close > 0:
            features["macd_hist_norm"] = (mh / last_close) * 10000
        else:
            features["macd_hist_norm"] = None

        # MA mesafesi
        ma20 = safe_float(sma(close, 20).iloc[-1]) if len(close) >= 20 else None
        ma50 = safe_float(sma(close, 50).iloc[-1]) if len(close) >= 50 else None

        if ma20 is not None and ma50 is not None and ma50 != 0:
            features["ma20_ma50_dist"] = ((ma20 / ma50) - 1) * 100
        else:
            features["ma20_ma50_dist"] = None

        # ATR yüzdesi
        atr_val = safe_float(atr(eur_df, 14).iloc[-1]) if len(eur_df) >= 15 else None
        if atr_val is not None and last_close and last_close > 0:
            features["atr_pct"] = (atr_val / last_close) * 100
        else:
            features["atr_pct"] = None

        # Momentum
        features["mom_5"] = momentum_pct(close, 5) if len(close) >= 6 else None
        features["mom_20"] = momentum_pct(close, 20) if len(close) >= 21 else None

    else:
        for f in ["rsi_14", "rsi_norm", "macd_hist", "macd_hist_norm",
                   "ma20_ma50_dist", "atr_pct", "mom_5", "mom_20"]:
            features[f] = None

    # ── Makro özellikler ──
    # DXY momentum
    if dxy_df is not None and not dxy_df.empty:
        features["dxy_ret_3"] = _safe_pct_change(dxy_df["Close"], 3)
        features["dxy_ret_5"] = _safe_pct_change(dxy_df["Close"], 5)
    else:
        features["dxy_ret_3"] = None
        features["dxy_ret_5"] = None

    # VIX seviye
    if vix_df is not None and not vix_df.empty:
        features["vix"] = safe_float(vix_df["Close"].iloc[-1])
        features["vix_norm"] = features["vix"] / 50 if features["vix"] is not None else None
    else:
        features["vix"] = None
        features["vix_norm"] = None

    # US-DE 2Y spread
    if us2y is not None and de2y is not None:
        features["spread_2y"] = us2y - de2y
    else:
        features["spread_2y"] = None

    # ── Rejim (one-hot) ──
    for r in ["RISK_ON", "RISK_OFF", "TREND", "RANGE"]:
        features[f"regime_{r}"] = 1.0 if market_regime == r else 0.0

    # ── Seasonality ──
    if eur_df is not None and not eur_df.empty and hasattr(eur_df.index, 'month'):
        try:
            features["month"] = float(eur_df.index[-1].month)
            features["weekday"] = float(eur_df.index[-1].weekday())
        except Exception:
            features["month"] = None
            features["weekday"] = None
    else:
        features["month"] = None
        features["weekday"] = None

    return features


def build_historical_features(eur_df, dxy_df, vix_df, min_lookback: int = 120) -> pd.DataFrame:
    """Tarihsel veri üzerinden rolling feature matrix oluşturur.

    Walk-forward validation ve model eğitimi için kullanılır.

    Returns:
        DataFrame: Her satır bir gün, her kolon bir feature.
        Ayrıca target kolonları: ret_1, ret_3, ret_5, ret_10
    """
    if eur_df is None or dxy_df is None or vix_df is None:
        return pd.DataFrame()

    close_eur = eur_df["Close"]
    close_dxy = dxy_df["Close"]
    close_vix = vix_df["Close"]

    # Ortak index
    df = pd.DataFrame({
        "eur": close_eur,
        "dxy": close_dxy,
        "vix": close_vix,
    }).dropna()

    if len(df) < min_lookback + 30:
        return pd.DataFrame()

    # Teknik
    df["rsi_14"] = rsi(df["eur"])
    df["macd_h"] = macd_hist(df["eur"])
    df["ma20"] = sma(df["eur"], 20)
    df["ma50"] = sma(df["eur"], 50)
    df["ma20_ma50_dist"] = ((df["ma20"] / df["ma50"]) - 1) * 100

    _atr = atr(eur_df, 14).reindex(df.index)
    df["atr_pct"] = (_atr / df["eur"]) * 100

    # Momentum
    df["mom_5"] = df["eur"].pct_change(5) * 100
    df["mom_20"] = df["eur"].pct_change(20) * 100

    # Makro
    df["dxy_ret_3"] = df["dxy"].pct_change(3) * 100
    df["dxy_ret_5"] = df["dxy"].pct_change(5) * 100
    df["vix_norm"] = df["vix"] / 50

    # Targets: ileri dönem getiri
    for h in [1, 3, 5, 10]:
        df[f"ret_{h}"] = df["eur"].pct_change(-h).shift(-h) * -100
        # NOT: pct_change(-h) ileriye bakar, -100 ile "düşüş = pozitif" convention

    # Yön hedefi (binary)
    for h in [1, 3, 5, 10]:
        df[f"dir_{h}"] = (df[f"ret_{h}"] > 0).astype(float)  # 1 = EUR düştü (satış doğru)

    # Temizle
    df = df.iloc[min_lookback:].dropna(subset=["rsi_14", "ma20_ma50_dist", "mom_5"])

    return df


FEATURE_COLUMNS = [
    "rsi_14", "macd_h", "ma20_ma50_dist", "atr_pct",
    "mom_5", "mom_20", "dxy_ret_3", "dxy_ret_5", "vix_norm",
]

TARGET_COLUMNS = ["ret_1", "ret_3", "ret_5", "ret_10"]
DIRECTION_COLUMNS = ["dir_1", "dir_3", "dir_5", "dir_10"]
