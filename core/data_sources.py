import os
import re
import functools
from io import StringIO
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import yfinance as yf


# ---------------------------------------------------------------------------
# Streamlit-agnostic cache decorator
# ---------------------------------------------------------------------------
# If running inside Streamlit, st.cache_data will be used automatically.
# Otherwise a simple functools.lru_cache fallback keeps the module testable
# and importable without any UI dependency.
# ---------------------------------------------------------------------------
def _make_cache(ttl: int):
    """Return a cache decorator.  Uses st.cache_data when available."""
    try:
        import streamlit as _st
        return _st.cache_data(ttl=ttl, show_spinner=False)
    except Exception:
        # Outside Streamlit → no caching (functions are called directly)
        def _passthrough(fn):
            @functools.wraps(fn)
            def wrapper(*a, **kw):
                return fn(*a, **kw)
            return wrapper
        return _passthrough


LOCAL_TZ = ZoneInfo("Europe/Istanbul")


def safe_float(x):
    try:
        if pd.isna(x):
            return None
        return float(x)
    except Exception:
        return None


def pct(a, b):
    if a is None or b is None:
        return None
    if a == 0:
        return None
    return (b / a - 1) * 100


def _http_get(url, params=None, timeout=20):
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0 Safari/537.36"
        )
    }
    return requests.get(url, params=params, timeout=timeout, headers=headers)


def get_fmp_api_key():
    try:
        import streamlit as _st
        key = _st.secrets.get("FMP_API_KEY", "")
        if key:
            return key
    except Exception:
        pass
    return os.getenv("FMP_API_KEY", "")


@_make_cache(ttl=300)
def get_yahoo(ticker, interval="1d", period="6mo"):
    try:
        df = yf.download(
            ticker,
            interval=interval,
            period=period,
            auto_adjust=True,
            progress=False,
            threads=False,
        )

        if df is None or df.empty:
            return None

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [c[0] for c in df.columns]

        needed = ["Open", "High", "Low", "Close"]
        for col in needed:
            if col not in df.columns:
                return None

        df = df.dropna(subset=needed).copy()
        if df.empty:
            return None

        return df
    except Exception:
        return None


@_make_cache(ttl=3600)
def get_us2y_with_source():
    try:
        url = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS2"
        r = _http_get(url, timeout=20)
        if r.status_code == 200 and r.text.strip():
            df = pd.read_csv(StringIO(r.text))
            if "DGS2" in df.columns:
                s = pd.to_numeric(df["DGS2"], errors="coerce").dropna()
                if not s.empty:
                    return {"value": float(s.iloc[-1]), "source": "FRED:DGS2", "status": "ok"}
    except Exception:
        pass

    try:
        url = (
            "https://home.treasury.gov/resource-center/data-chart-center/"
            "interest-rates/pages/xmlview?data=daily_treasury_yield_curve"
        )
        r = _http_get(url, timeout=20)
        if r.status_code == 200 and r.text:
            matches = re.findall(r"BC_2YEAR[^0-9]*([\d\.]+)", r.text)
            if matches:
                return {"value": float(matches[-1]), "source": "USTREASURY:BC_2YEAR", "status": "ok"}
    except Exception:
        pass

    return {"value": None, "source": None, "status": "missing"}


@_make_cache(ttl=3600)
def get_us10y_with_source():
    try:
        url = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10"
        r = _http_get(url, timeout=20)
        if r.status_code == 200 and r.text.strip():
            df = pd.read_csv(StringIO(r.text))
            if "DGS10" in df.columns:
                s = pd.to_numeric(df["DGS10"], errors="coerce").dropna()
                if not s.empty:
                    return {"value": float(s.iloc[-1]), "source": "FRED:DGS10", "status": "ok"}
    except Exception:
        pass

    return {"value": None, "source": None, "status": "missing"}


@_make_cache(ttl=3600)
def get_de2y_with_source():
    try:
        url = "https://api.statistiken.bundesbank.de/rest/data/BBSSY/D.REN.EUR.A610.000000WT0202.A"
        r = _http_get(url, params={"format": "sdmx_csv"}, timeout=20)
        if r.status_code == 200 and r.text.strip():
            df = pd.read_csv(StringIO(r.text))
            obs_cols = [c for c in df.columns if c.upper() == "OBS_VALUE"]
            if not obs_cols:
                obs_cols = [c for c in df.columns if "OBS" in c.upper()]
            if obs_cols:
                s = pd.to_numeric(df[obs_cols[0]], errors="coerce").dropna()
                if not s.empty:
                    return {"value": float(s.iloc[-1]), "source": "BUNDESBANK:DE2Y", "status": "ok"}
    except Exception:
        pass

    try:
        url = (
            "https://data-api.ecb.europa.eu/service/data/"
            "YC/B.U2.EUR.4F.G_N_A.SV_C_YM.SR_2Y"
        )
        r = _http_get(url, params={"format": "csvdata"}, timeout=20)
        if r.status_code == 200 and r.text.strip():
            df = pd.read_csv(StringIO(r.text))
            numeric_cols = []
            for col in df.columns:
                sample = pd.to_numeric(df[col], errors="coerce")
                if sample.notna().sum() > 0:
                    numeric_cols.append(col)
            if numeric_cols:
                s = pd.to_numeric(df[numeric_cols[-1]], errors="coerce").dropna()
                if not s.empty:
                    return {"value": float(s.iloc[-1]), "source": "ECB:DE2Y", "status": "ok"}
    except Exception:
        pass

    return {"value": None, "source": None, "status": "missing"}


@_make_cache(ttl=3600)
def get_de10y_with_source():
    try:
        url = (
            "https://data-api.ecb.europa.eu/service/data/"
            "YC/B.U2.EUR.4F.G_N_A.SV_C_YM.SR_10Y"
        )
        r = _http_get(url, params={"format": "csvdata"}, timeout=20)
        if r.status_code == 200 and r.text.strip():
            df = pd.read_csv(StringIO(r.text))
            numeric_cols = []
            for col in df.columns:
                sample = pd.to_numeric(df[col], errors="coerce")
                if sample.notna().sum() > 0:
                    numeric_cols.append(col)
            if numeric_cols:
                s = pd.to_numeric(df[numeric_cols[-1]], errors="coerce").dropna()
                if not s.empty:
                    return {"value": float(s.iloc[-1]), "source": "ECB:DE10Y", "status": "ok"}
    except Exception:
        pass

    return {"value": None, "source": None, "status": "missing"}


def _is_high_impact(impact_value):
    if impact_value is None:
        return False
    text = str(impact_value).strip().lower()
    if text in {"high", "3", "3.0"}:
        return True
    try:
        return float(text) >= 3
    except Exception:
        return "high" in text


def _is_relevant_macro_event(row):
    country = str(row.get("country", "")).upper()
    currency = str(row.get("currency", "")).upper()
    event_name = str(row.get("event", "")).lower()

    important_countries = {"US", "USA", "EU", "EA", "DE", "GERMANY", "EUROZONE"}
    important_currencies = {"USD", "EUR"}

    keywords = [
        "cpi", "inflation", "pce", "ppi", "nfp", "payrolls", "unemployment",
        "fomc", "fed", "ecb", "lagarde", "powell", "interest rate", "rate decision",
        "pmi", "gdp", "retail sales", "ism", "consumer confidence",
    ]

    return (
        country in important_countries
        or currency in important_currencies
        or any(k in event_name for k in keywords)
    )


@_make_cache(ttl=1800)
def get_macro_events_with_source():
    api_key = get_fmp_api_key()
    if not api_key:
        return {"events": [], "source": None, "status": "missing"}

    try:
        today = datetime.now(LOCAL_TZ).date()
        end_day = today + timedelta(days=7)

        url = "https://financialmodelingprep.com/api/v3/economic_calendar"
        params = {
            "from": today.isoformat(),
            "to": end_day.isoformat(),
            "apikey": api_key,
        }

        r = _http_get(url, params=params, timeout=20)
        if r.status_code != 200:
            return {"events": [], "source": "FMP", "status": "missing"}

        data = r.json()
        if not isinstance(data, list):
            return {"events": [], "source": "FMP", "status": "missing"}

        events = []
        for row in data:
            if not isinstance(row, dict):
                continue
            if not _is_relevant_macro_event(row):
                continue
            if not _is_high_impact(row.get("impact")):
                continue

            date_raw = row.get("date")
            if not date_raw:
                continue

            events.append({
                "date": str(date_raw),
                "country": row.get("country"),
                "currency": row.get("currency"),
                "event": row.get("event"),
                "impact": row.get("impact"),
                "actual": row.get("actual"),
                "previous": row.get("previous"),
                "consensus": row.get("estimate") or row.get("forecast"),
            })

        events = sorted(events, key=lambda x: x["date"])
        return {"events": events, "source": "FMP:EconomicCalendar", "status": "ok" if events else "empty"}
    except Exception:
        return {"events": [], "source": "FMP:EconomicCalendar", "status": "missing"}


def build_data_quality(checks: dict):
    ok_count = sum(1 for v in checks.values() if v)
    total = len(checks)
    score = round((ok_count / total) * 100, 1) if total else 0.0

    if score >= 90:
        label = "Yüksek"
    elif score >= 65:
        label = "Orta"
    else:
        label = "Düşük"

    missing = [k for k, v in checks.items() if not v]

    return {
        "score": score,
        "label": label,
        "ok_count": ok_count,
        "total": total,
        "checks": checks,
        "missing": missing,
    }


@_make_cache(ttl=300)
def get_market_bundle():
    eur_1d = get_yahoo("EURUSD=X", "1d", "10y")
    eur_4h = get_yahoo("EURUSD=X", "4h", "180d")
    dxy_df = get_yahoo("DX-Y.NYB", "1d", "10y")
    vix_df = get_yahoo("^VIX", "1d", "10y")

    us2y_info = get_us2y_with_source()
    us10y_info = get_us10y_with_source()
    de2y_info = get_de2y_with_source()
    de10y_info = get_de10y_with_source()
    macro_info = get_macro_events_with_source()

    spot = safe_float(eur_1d["Close"].iloc[-1]) if eur_1d is not None and not eur_1d.empty else None

    support = None
    resistance = None
    if eur_1d is not None and not eur_1d.empty:
        if len(eur_1d) >= 60:
            support = safe_float(eur_1d["Low"].tail(60).min())
            resistance = safe_float(eur_1d["High"].tail(60).max())
        else:
            support = safe_float(eur_1d["Low"].min())
            resistance = safe_float(eur_1d["High"].max())

    dxy_pct = None
    if dxy_df is not None and len(dxy_df) >= 4:
        dxy_start = safe_float(dxy_df["Close"].iloc[-4])
        dxy_end = safe_float(dxy_df["Close"].iloc[-1])
        dxy_pct = pct(dxy_start, dxy_end)

    vix_val = safe_float(vix_df["Close"].iloc[-1]) if vix_df is not None and not vix_df.empty else None

    checks = {
        "EURUSD_1D": eur_1d is not None and not eur_1d.empty,
        "EURUSD_4H": eur_4h is not None and not eur_4h.empty,
        "DXY": dxy_df is not None and not dxy_df.empty,
        "VIX": vix_df is not None and not vix_df.empty,
        "US2Y": us2y_info["value"] is not None,
        "US10Y": us10y_info["value"] is not None,
        "DE2Y": de2y_info["value"] is not None,
        "DE10Y": de10y_info["value"] is not None,
    }

    return {
        "eur_1d": eur_1d,
        "eur_4h": eur_4h,
        "dxy_df": dxy_df,
        "vix_df": vix_df,
        "spot": spot,
        "support": support,
        "resistance": resistance,
        "dxy_pct": dxy_pct,
        "vix": vix_val,
        "us2y": us2y_info["value"],
        "us10y": us10y_info["value"],
        "de2y": de2y_info["value"],
        "de10y": de10y_info["value"],
        "us2y_source": us2y_info["source"],
        "us10y_source": us10y_info["source"],
        "de2y_source": de2y_info["source"],
        "de10y_source": de10y_info["source"],
        "macro_events": macro_info["events"],
        "macro_source": macro_info["source"],
        "macro_status": macro_info["status"],
        "data_quality": build_data_quality(checks),
    }