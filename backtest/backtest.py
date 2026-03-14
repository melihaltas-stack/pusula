import pandas as pd

from core.indicators import detect_trend_regime
from backtest.confidence import add_confidence_to_horizons, format_probability_with_ci


def _normalize_close_series(df):
    if df is None or df.empty or "Close" not in df.columns:
        return None

    series = pd.to_numeric(df["Close"], errors="coerce").dropna().copy()
    if isinstance(series.index, pd.DatetimeIndex) and series.index.tz is not None:
        series.index = series.index.tz_convert("UTC").tz_localize(None)
    return series


def _band_from_ede(ede):
    if ede >= 65:
        return "65+"
    if ede >= 52:
        return "52-64"
    if ede >= 40:
        return "40-51"
    return "0-39"


def _regime_from_ma(close_series, idx):
    if idx < 100:
        return "SIDEWAYS"

    ma20 = close_series.iloc[idx-19:idx+1].mean()
    ma50 = close_series.iloc[idx-49:idx+1].mean()
    ma100 = close_series.iloc[idx-99:idx+1].mean()

    if ma20 > ma50 > ma100:
        return "UP"
    if ma20 < ma50 < ma100:
        return "DOWN"
    return "SIDEWAYS"


def _compute_proxy_ede(eur_close, dxy_close, vix_close, idx):
    eur_ret = eur_close.pct_change().iloc[idx]
    dxy_ret = dxy_close.pct_change().iloc[idx]
    vix_val = vix_close.iloc[idx]

    score_dxy = max(0, min(100, 50 - dxy_ret * 2000))
    score_risk = max(0, min(100, 100 - vix_val))
    score_tech = max(0, min(100, 50 + eur_ret * 2000))

    ede = score_dxy * 0.4 + score_risk * 0.2 + score_tech * 0.4
    return float(ede)


def build_probability_summary(eur_df, dxy_df, vix_df, current_ede, current_regime):
    if eur_df is None or dxy_df is None or vix_df is None:
        return {
            "sample_size": 0,
            "horizons": {},
            "summary_text": "Olasılık analizi için veri yetersiz."
        }

    eur_close = _normalize_close_series(eur_df)
    dxy_close = _normalize_close_series(dxy_df)
    vix_close = _normalize_close_series(vix_df)
    if eur_close is None or dxy_close is None or vix_close is None:
        return {
            "sample_size": 0,
            "horizons": {},
            "summary_text": "Olasılık analizi için veri yetersiz."
        }

    df = pd.DataFrame({
        "eur_close": eur_close,
        "dxy_close": dxy_close,
        "vix_close": vix_close,
    }).dropna()

    if len(df) < 300:
        return {
            "sample_size": 0,
            "horizons": {},
            "summary_text": "Olasılık analizi için yeterli tarihsel veri yok."
        }

    current_band = _band_from_ede(current_ede)

    rows = []
    max_horizon = 30

    for idx in range(120, len(df) - max_horizon):
        ede = _compute_proxy_ede(df["eur_close"], df["dxy_close"], df["vix_close"], idx)
        band = _band_from_ede(ede)
        regime = _regime_from_ma(df["eur_close"], idx)

        if band != current_band or regime != current_regime:
            continue

        row = {
            "idx": idx,
            "ede": ede,
            "band": band,
            "regime": regime,
        }

        for horizon in [3, 5, 10, 20, 30]:
            future_ret = (df["eur_close"].iloc[idx + horizon] / df["eur_close"].iloc[idx] - 1) * 100
            row[f"ret_{horizon}"] = future_ret

        rows.append(row)

    hist = pd.DataFrame(rows)
    if hist.empty:
        return {
            "sample_size": 0,
            "horizons": {},
            "summary_text": "Benzer koşul bulunamadı."
        }

    horizons = {}
    for horizon in [3, 5, 10, 20, 30]:
        series = hist[f"ret_{horizon}"]
        down_prob = float((series < 0).mean() * 100)
        avg_ret = float(series.mean())
        horizons[horizon] = {
            "down_probability": round(down_prob, 1),
            "avg_return": round(avg_ret, 2),
        }

    # Güven aralığı ekle (Faz 3)
    horizons = add_confidence_to_horizons(horizons, len(hist))

    # Güven aralıklı özet metin
    h3 = horizons[3]
    h5 = horizons[5]
    h10 = horizons[10]

    ci_text_3 = format_probability_with_ci(h3["down_probability"], h3["ci_lower"], h3["ci_upper"], h3["reliable"])
    ci_text_5 = format_probability_with_ci(h5["down_probability"], h5["ci_lower"], h5["ci_upper"], h5["reliable"])
    ci_text_10 = format_probability_with_ci(h10["down_probability"], h10["ci_lower"], h10["ci_upper"], h10["reliable"])

    summary_text = (
        f"Benzer koşul sayısı: {len(hist)} | "
        f"3G düşüş: {ci_text_3} | "
        f"5G: {ci_text_5} | "
        f"10G: {ci_text_10}"
    )

    return {
        "sample_size": int(len(hist)),
        "horizons": horizons,
        "summary_text": summary_text,
    }
