import os
import logging
import pandas as pd
from datetime import datetime

_log = logging.getLogger(__name__)


LOG_FILE = "decision_log.csv"


# ------------------------------------------------
# Günlük kararı kaydet
# ------------------------------------------------
def log_daily_decision(data):

    row = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "active_horizon": data.get("active_horizon"),
        "active_horizon_label": data.get("active_horizon_label"),
        "ede": data["ede"],
        "base_ede": data.get("horizon_views", {}).get(data.get("active_horizon", "short_term"), {}).get("base_ede"),
        "trend": data["trend_regime"],
        "spot": data["spot"],
        "confidence_label": data.get("confidence_label"),
        "data_quality_score": data.get("data_quality_score"),
        "prob_sample_size": data.get("probability", {}).get("sample_size"),
        "forecast_sample_size": data.get("forecast", {}).get("sample_size"),
        "forecast_summary": data.get("forecast", {}).get("summary"),
        "hybrid_performance_summary": data.get("hybrid_performance", {}).get("summary"),
        "positioning_score": data.get("scores", {}).get("Positioning"),
        "spread_momentum_score": data.get("scores", {}).get("SpreadMomentum"),
        "cross_asset_score": data.get("scores", {}).get("CrossAsset"),
        "dxy_score": data.get("scores", {}).get("DXY"),
        "macro_score": data.get("scores", {}).get("MacroRisk"),
        "momentum_score": data.get("scores", {}).get("Momentum"),
        "fast_mode": bool(data.get("fast_mode")),
        "daily_units": data["sale_plan"]["daily_units"],
        "morning_units": data["sale_plan"]["morning_units"],
        "afternoon_units": data["sale_plan"]["afternoon_units"],
        "decision": data["sale_plan"]["plan_label"],
        "report_text": data.get("operation_summary"),
    }

    df = pd.DataFrame([row])

    if os.path.exists(LOG_FILE):
        df_old = pd.read_csv(LOG_FILE)
        df = pd.concat([df_old, df], ignore_index=True)

    df.to_csv(LOG_FILE, index=False)

    return LOG_FILE


# ------------------------------------------------
# Karar günlüğünü oku
# ------------------------------------------------
def read_decision_log():

    if not os.path.exists(LOG_FILE):
        return pd.DataFrame()

    try:
        df = pd.read_csv(LOG_FILE)
        return df
    except (OSError, pd.errors.ParserError, pd.errors.EmptyDataError) as e:
        _log.warning("read_decision_log: log dosyası okunamadı path=%s err=%s", LOG_FILE, e)
        return pd.DataFrame()


# ------------------------------------------------
# Treasury performans metrikleri
# ------------------------------------------------
def build_treasury_metrics(df):

    if df.empty:
        return {
            "avg_sale_units": 0,
            "hit_rate": 0,
            "protected_value": 0,
            "avg_advantage": 0,
            "avg_ede": 0,
            "avg_data_quality": 0,
            "high_confidence_rate": 0,
        }

    avg_sale_units = round(df["daily_units"].mean(), 1)

    # basit proxy: yüksek EDE günleri başarılı kabul
    good_days = df[df["ede"] >= 60]

    hit_rate = 0
    if len(df) > 0:
        hit_rate = round(len(good_days) / len(df) * 100, 1)

    # placeholder değer
    avg_advantage = round((df["ede"].mean() - 50) * 0.02, 2)

    protected_value = round(avg_advantage * 100000, 0)
    avg_ede = round(df["ede"].mean(), 1) if "ede" in df.columns else 0
    avg_data_quality = round(df["data_quality_score"].dropna().mean(), 1) if "data_quality_score" in df.columns and df["data_quality_score"].notna().any() else 0
    high_confidence_rate = 0
    if "confidence_label" in df.columns and len(df) > 0:
        high_confidence_rate = round((df["confidence_label"].fillna("") == "Yüksek").mean() * 100, 1)

    return {
        "avg_sale_units": avg_sale_units,
        "hit_rate": hit_rate,
        "protected_value": protected_value,
        "avg_advantage": avg_advantage,
        "avg_ede": avg_ede,
        "avg_data_quality": avg_data_quality,
        "high_confidence_rate": high_confidence_rate,
    }


def build_factor_contribution_summary(df, lookback_days: int = 30):

    if df.empty:
        return {
            "window_days": lookback_days,
            "sample_size": 0,
            "leaders": [],
            "summary": "Son 30 gün için factor verisi yok.",
        }

    work = df.copy()
    if "date" in work.columns:
        work["date"] = pd.to_datetime(work["date"], errors="coerce")
        cutoff = pd.Timestamp(datetime.now().date()) - pd.Timedelta(days=lookback_days - 1)
        work = work[work["date"].notna() & (work["date"] >= cutoff)].copy()

    if work.empty:
        return {
            "window_days": lookback_days,
            "sample_size": 0,
            "leaders": [],
            "summary": "Son 30 gün için factor verisi yok.",
        }

    factor_columns = {
        "Positioning": "positioning_score",
        "Spread Momentum": "spread_momentum_score",
        "Cross Asset": "cross_asset_score",
        "DXY": "dxy_score",
        "Makro": "macro_score",
        "Momentum": "momentum_score",
    }

    leaders = []
    for label, column in factor_columns.items():
        if column not in work.columns:
            continue
        series = pd.to_numeric(work[column], errors="coerce").dropna()
        if series.empty:
            continue
        leaders.append(
            {
                "label": label,
                "avg_score": round(series.mean(), 1),
                "deviation": round((series.mean() - 50), 1),
                "high_days": int((series >= 60).sum()),
                "low_days": int((series <= 40).sum()),
            }
        )

    leaders = sorted(leaders, key=lambda item: abs(item["deviation"]), reverse=True)
    top = leaders[:3]

    if not top:
        summary = "Son 30 gün için factor katkı özeti üretilemedi."
    else:
        summary = " | ".join(
            f"{item['label']}: ort {item['avg_score']} ({item['deviation']:+.1f})"
            for item in top
        )

    return {
        "window_days": lookback_days,
        "sample_size": int(len(work)),
        "leaders": top,
        "summary": summary,
    }
