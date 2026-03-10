import os
import pandas as pd
from datetime import datetime


LOG_FILE = "decision_log.csv"


# ------------------------------------------------
# Günlük kararı kaydet
# ------------------------------------------------
def log_daily_decision(data):

    row = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "ede": data["ede"],
        "trend": data["trend_regime"],
        "spot": data["spot"],
        "daily_units": data["sale_plan"]["daily_units"],
        "morning_units": data["sale_plan"]["morning_units"],
        "afternoon_units": data["sale_plan"]["afternoon_units"],
        "decision": data["sale_plan"]["plan_label"]
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
    except:
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
            "avg_advantage": 0
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

    return {
        "avg_sale_units": avg_sale_units,
        "hit_rate": hit_rate,
        "protected_value": protected_value,
        "avg_advantage": avg_advantage
    }