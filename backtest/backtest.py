import pandas as pd

from backtest.confidence import format_probability_with_ci, wilson_interval
from forecast.features import FEATURE_COLUMNS, build_feature_row, build_historical_features
from forecast.forecast import find_similar_periods


def _normalize_close_series(df):
    if df is None or df.empty or "Close" not in df.columns:
        return None

    series = pd.to_numeric(df["Close"], errors="coerce").dropna().copy()
    if isinstance(series.index, pd.DatetimeIndex) and series.index.tz is not None:
        series.index = series.index.tz_convert("UTC").tz_localize(None)
    return series


def _build_extra_horizons(df):
    extra = df.copy()
    for horizon in [20, 30]:
        extra[f"ret_{horizon}"] = ((extra["eur"].shift(-horizon) / extra["eur"]) - 1) * -100
        extra[f"dir_{horizon}"] = (extra[f"ret_{horizon}"] > 0).astype(float)
    return extra


def _select_neighbors(eur_df, dxy_df, vix_df, current_regime, spread_2y_history=None, spx_df=None, eurostoxx_df=None, gold_df=None, oil_df=None, cross_asset=None, cot_positioning=None):
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
    if hist_df.empty:
        return pd.DataFrame(), pd.DataFrame()

    current_features = build_feature_row(
        eur_df,
        dxy_df,
        vix_df,
        spread_2y_history=spread_2y_history,
        cross_asset=cross_asset,
        cot_positioning=cot_positioning,
        market_regime="TREND" if current_regime in {"UP", "DOWN"} else "RANGE",
    )
    neighbors = find_similar_periods(current_features, hist_df)
    if neighbors.empty:
        return pd.DataFrame(), pd.DataFrame()

    feature_cols = [col for col in FEATURE_COLUMNS if col in hist_df.columns]
    if not feature_cols:
        return neighbors, hist_df

    current_trend_flag = 1 if current_regime == "UP" else -1 if current_regime == "DOWN" else 0
    trend_col = "ma20_ma50_dist"
    if trend_col in neighbors.columns:
        trend_sign = neighbors[trend_col].fillna(0).apply(lambda value: 1 if value > 0 else -1 if value < 0 else 0)
        aligned = neighbors[trend_sign == current_trend_flag]
        if len(aligned) >= 12:
            neighbors = aligned

    return neighbors, hist_df


def _summarize_horizon(series):
    valid = pd.to_numeric(series, errors="coerce").dropna()
    if valid.empty:
        return None

    down_count = int((valid > 0).sum())
    total = int(len(valid))
    ci = wilson_interval(down_count, total)
    avg_ret = float(valid.mean())

    return {
        "down_probability": ci["point"],
        "avg_return": round(avg_ret, 2),
        "ci_lower": ci["lower"],
        "ci_upper": ci["upper"],
        "ci_width": ci["ci_width"],
        "reliable": ci["reliable"],
        "sample_size": total,
    }


def build_probability_summary(
    eur_df,
    dxy_df,
    vix_df,
    current_ede,
    current_regime,
    spread_2y_history=None,
    spx_df=None,
    eurostoxx_df=None,
    gold_df=None,
    oil_df=None,
    cross_asset=None,
    cot_positioning=None,
):
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

    neighbors, hist_df = _select_neighbors(
        eur_df,
        dxy_df,
        vix_df,
        current_regime,
        spread_2y_history=spread_2y_history,
        spx_df=spx_df,
        eurostoxx_df=eurostoxx_df,
        gold_df=gold_df,
        oil_df=oil_df,
        cross_asset=cross_asset,
        cot_positioning=cot_positioning,
    )
    if neighbors.empty or hist_df.empty:
        return {
            "sample_size": 0,
            "horizons": {},
            "summary_text": "Benzer koşul bulunamadı."
        }

    base_df = pd.DataFrame({
        "eur": eur_close,
        "dxy": dxy_close,
        "vix": vix_close,
    }).dropna()
    base_df = _build_extra_horizons(base_df)
    extended = hist_df.join(base_df[[f"ret_{h}" for h in [20, 30]] + [f"dir_{h}" for h in [20, 30]]], how="left")
    matched = extended.loc[neighbors.index].copy()

    horizons = {}
    for horizon in [3, 5, 10, 20, 30]:
        summary = _summarize_horizon(matched.get(f"ret_{horizon}"))
        if summary is not None:
            horizons[horizon] = summary

    if not horizons:
        return {
            "sample_size": 0,
            "horizons": {},
            "summary_text": "Benzer koşul bulunamadı."
        }

    # Güven aralıklı özet metin
    h3 = horizons.get(3)
    h5 = horizons.get(5)
    h10 = horizons.get(10)

    if not all([h3, h5, h10]):
        return {
            "sample_size": int(len(matched)),
            "horizons": horizons,
            "summary_text": f"Benzer koşul sayısı: {len(matched)} | Bazı horizonlar için veri yetersiz."
        }

    ci_text_3 = format_probability_with_ci(h3["down_probability"], h3["ci_lower"], h3["ci_upper"], h3["reliable"])
    ci_text_5 = format_probability_with_ci(h5["down_probability"], h5["ci_lower"], h5["ci_upper"], h5["reliable"])
    ci_text_10 = format_probability_with_ci(h10["down_probability"], h10["ci_lower"], h10["ci_upper"], h10["reliable"])

    summary_text = (
        f"Benzer koşul sayısı: {len(matched)} | "
        f"3G düşüş: {ci_text_3} | "
        f"5G: {ci_text_5} | "
        f"10G: {ci_text_10}"
    )

    return {
        "sample_size": int(len(matched)),
        "horizons": horizons,
        "summary_text": summary_text,
    }
