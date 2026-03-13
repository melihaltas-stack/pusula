import os
import re
import logging
import time
from io import StringIO
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import streamlit as st
import yfinance as yf

from core.validators import validate_market_bundle
from freshness import stamp, build_bundle_freshness

LOCAL_TZ = ZoneInfo("Europe/Istanbul")
logger = logging.getLogger(__name__)
CACHE_DIR = Path(os.getenv("SELVESE_CACHE_DIR", "/tmp/selvese-pusula-cache"))
CACHE_NAMESPACE = os.getenv("SELVESE_CACHE_NAMESPACE", "prod").strip() or "prod"
CACHE_VERSION = "v1"

# Roadmap Faz 1 TTL kuralları (saniye)
_TTL_SPOT   = 60      # spot / OHLCV
_TTL_RATES  = 1800    # faiz oranları (30 dk)
_TTL_MACRO  = 3600    # makro takvim (1 saat)


def safe_float(x):
    try:
        if pd.isna(x):
            return None
        return float(x)
    except (TypeError, ValueError):
        return None


def pct(a, b):
    if a is None or b is None:
        return None
    if a == 0:
        return None
    return (b / a - 1) * 100


def _ensure_ohlc(df):
    if df is None or df.empty:
        return None

    frame = df.copy()
    if isinstance(frame.columns, pd.MultiIndex):
        frame.columns = [c[0] for c in frame.columns]

    if "Close" not in frame.columns:
        close_candidates = ["close", "CLOSE", "OBS_VALUE", "value", "Value"]
        for col in close_candidates:
            if col in frame.columns:
                frame["Close"] = pd.to_numeric(frame[col], errors="coerce")
                break

    if "Close" not in frame.columns:
        return None

    frame["Close"] = pd.to_numeric(frame["Close"], errors="coerce")

    for col in ["Open", "High", "Low"]:
        if col not in frame.columns:
            frame[col] = frame["Close"]
        else:
            frame[col] = pd.to_numeric(frame[col], errors="coerce")

    frame = frame[["Open", "High", "Low", "Close"]].dropna().copy()
    if frame.empty:
        return None

    if not isinstance(frame.index, pd.DatetimeIndex):
        frame.index = pd.to_datetime(frame.index, errors="coerce")
        frame = frame[~frame.index.isna()].copy()

    frame = frame.sort_index()
    return frame


def _resample_to_4h(df):
    frame = _ensure_ohlc(df)
    if frame is None or frame.empty:
        return None

    if frame.index.tz is not None:
        frame.index = frame.index.tz_convert("UTC").tz_localize(None)

    resampled = pd.DataFrame(
        {
            "Open": frame["Open"].resample("4h").first(),
            "High": frame["High"].resample("4h").max(),
            "Low": frame["Low"].resample("4h").min(),
            "Close": frame["Close"].resample("4h").last(),
        }
    ).dropna()

    return _ensure_ohlc(resampled)


def _build_inverse_fx_proxy(df, base_level=100.0):
    frame = _ensure_ohlc(df)
    if frame is None or frame.empty:
        return None

    proxy = frame.copy()
    for col in ["Open", "High", "Low", "Close"]:
        proxy[col] = pd.to_numeric(proxy[col], errors="coerce")

    inverse = pd.DataFrame(index=proxy.index)
    inverse["Open"] = base_level / proxy["Open"]
    inverse["Close"] = base_level / proxy["Close"]
    inverse["High"] = base_level / proxy["Low"]
    inverse["Low"] = base_level / proxy["High"]
    inverse = inverse.replace([pd.NA, pd.NaT, float("inf"), float("-inf")], pd.NA).dropna()
    return _ensure_ohlc(inverse)


def _cache_file(cache_key, suffix):
    CACHE_DIR.mkdir(exist_ok=True)
    safe_key = re.sub(r"[^A-Za-z0-9_.-]+", "_", cache_key)
    return CACHE_DIR / f"{CACHE_VERSION}_{CACHE_NAMESPACE}_{safe_key}.{suffix}"


def _is_test_payload(payload):
    if not isinstance(payload, dict):
        return False
    source = str(payload.get("source", ""))
    status = str(payload.get("status", ""))
    return source.startswith("TEST:") or status == "test"


def _is_usable_prod_payload(payload):
    return not (CACHE_NAMESPACE == "prod" and _is_test_payload(payload))


def _save_dataframe_cache(cache_key, df):
    if df is None or df.empty:
        return
    path = _cache_file(cache_key, "csv")
    try:
        df.to_csv(path)
    except OSError as e:
        logger.warning("dataframe cache yazilamadi key=%s err=%s", cache_key, e)


def _load_dataframe_cache(cache_key):
    path = _cache_file(cache_key, "csv")
    if not path.exists():
        return None, None
    try:
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        if df.empty:
            return None, None
        return df, datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    except (OSError, pd.errors.ParserError, ValueError) as e:
        logger.warning("dataframe cache okunamadi key=%s err=%s", cache_key, e)
        return None, None


def _save_dict_cache(cache_key, payload):
    path = _cache_file(cache_key, "json")
    try:
        pd.Series(payload).to_json(path, force_ascii=False)
    except OSError as e:
        logger.warning("dict cache yazilamadi key=%s err=%s", cache_key, e)


def _load_dict_cache(cache_key):
    path = _cache_file(cache_key, "json")
    if not path.exists():
        return None, None
    try:
        data = pd.read_json(path, typ="series").to_dict()
        if not _is_usable_prod_payload(data):
            logger.warning("dict cache yoksayildi key=%s namespace=%s", cache_key, CACHE_NAMESPACE)
            return None, None
        return data, datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    except (OSError, ValueError) as e:
        logger.warning("dict cache okunamadi key=%s err=%s", cache_key, e)
        return None, None


def _load_list_cache(cache_key):
    path = _cache_file(cache_key, "json")
    if not path.exists():
        return None, None
    try:
        data = pd.read_json(path)
        records = data.to_dict(orient="records")
        return records, datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    except (OSError, ValueError) as e:
        logger.warning("list cache okunamadi key=%s err=%s", cache_key, e)
        return None, None


def _save_list_cache(cache_key, items):
    path = _cache_file(cache_key, "json")
    try:
        pd.DataFrame(items).to_json(path, orient="records", force_ascii=False)
    except OSError as e:
        logger.warning("list cache yazilamadi key=%s err=%s", cache_key, e)


def _http_get(url, params=None, timeout=20):
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0 Safari/537.36"
        )
    }
    return requests.get(url, params=params, timeout=timeout, headers=headers)


def _http_get_with_retry(url, params=None, timeouts=(10, 20, 30), backoff_seconds=(1.0, 2.0)):
    last_error = None
    for attempt, timeout in enumerate(timeouts, start=1):
        try:
            response = _http_get(url, params=params, timeout=timeout)
            if response.status_code == 429:
                raise requests.exceptions.HTTPError("429 Too Many Requests")
            return response
        except requests.exceptions.RequestException as e:
            last_error = e
            if attempt <= len(backoff_seconds):
                time.sleep(backoff_seconds[attempt - 1])
    if last_error:
        raise last_error
    raise requests.exceptions.RequestException("HTTP request failed without explicit error")


def _download_ecb_eurusd_history():
    url = "https://data-api.ecb.europa.eu/service/data/EXR/D.USD.EUR.SP00.A"
    response = _http_get_with_retry(url, params={"format": "csvdata"})
    df = pd.read_csv(StringIO(response.text))
    date_col = next((c for c in df.columns if c.upper() in {"TIME_PERIOD", "DATE"}), None)
    value_col = next((c for c in df.columns if c.upper() == "OBS_VALUE"), None)
    if not date_col or not value_col:
        return None
    series = pd.DataFrame(
        {"Close": pd.to_numeric(df[value_col], errors="coerce").values},
        index=pd.to_datetime(df[date_col], errors="coerce"),
    ).dropna()
    return _ensure_ohlc(series)


def _download_fred_close_history(series_id, start_date=None):
    params = {}
    if start_date:
        params["cosd"] = start_date
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    response = _http_get_with_retry(url, params=params, timeouts=(10, 15, 20))
    df = pd.read_csv(StringIO(response.text))
    if "DATE" not in df.columns or series_id not in df.columns:
        return None
    series = pd.DataFrame(
        {"Close": pd.to_numeric(df[series_id], errors="coerce").values},
        index=pd.to_datetime(df["DATE"], errors="coerce"),
    ).dropna()
    return _ensure_ohlc(series)


def _download_fred_data_history(series_id):
    url = f"https://fred.stlouisfed.org/data/{series_id}"
    response = _http_get_with_retry(url, timeouts=(10, 15, 20))
    rows = []
    for line in response.text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "|" not in line:
            continue
        date_text, value_text = [part.strip() for part in line.split("|", 1)]
        if value_text in {".", ""}:
            continue
        rows.append((date_text, value_text))

    if not rows:
        return None

    series = pd.DataFrame(
        {"Close": pd.to_numeric([v for _, v in rows], errors="coerce")},
        index=pd.to_datetime([d for d, _ in rows], errors="coerce"),
    ).dropna()
    return _ensure_ohlc(series)


def _download_treasury_par_yield_table():
    month = datetime.now(LOCAL_TZ).strftime("%Y%m")
    url = (
        "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
        f"TextView?field_tdr_date_value_month={month}&type=daily_treasury_yield_curve"
    )
    response = _http_get_with_retry(url, timeouts=(10, 15, 20))
    html = response.text

    header_match = re.search(r"<thead.*?</thead>", html, flags=re.IGNORECASE | re.DOTALL)
    body_match = re.search(r"<tbody.*?</tbody>", html, flags=re.IGNORECASE | re.DOTALL)
    if not header_match or not body_match:
        return None

    header_cells = re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", header_match.group(0), flags=re.IGNORECASE | re.DOTALL)
    headers = [re.sub(r"<.*?>", "", cell).strip() for cell in header_cells]
    if not headers:
        return None

    rows = []
    for row_html in re.findall(r"<tr[^>]*>(.*?)</tr>", body_match.group(0), flags=re.IGNORECASE | re.DOTALL):
        cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row_html, flags=re.IGNORECASE | re.DOTALL)
        values = [re.sub(r"<.*?>", "", cell).strip() for cell in cells]
        if len(values) == len(headers):
            rows.append(values)

    if not rows:
        return None

    table = pd.DataFrame(rows, columns=headers)
    normalized = {str(col).strip(): col for col in table.columns}
    if "Date" in normalized and "2 Yr" in normalized and "10 Yr" in normalized:
        return table.rename(columns={normalized["Date"]: "Date", normalized["2 Yr"]: "2 Yr", normalized["10 Yr"]: "10 Yr"})
    return None


def _download_cboe_vix_history():
    url = "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv"
    response = _http_get_with_retry(url)
    df = pd.read_csv(StringIO(response.text))
    rename_map = {c: c.title() for c in df.columns}
    df = df.rename(columns=rename_map)
    date_col = "Date" if "Date" in df.columns else None
    if not date_col:
        return None
    normalized = pd.DataFrame(
        {
            "Open": pd.to_numeric(df.get("Open"), errors="coerce"),
            "High": pd.to_numeric(df.get("High"), errors="coerce"),
            "Low": pd.to_numeric(df.get("Low"), errors="coerce"),
            "Close": pd.to_numeric(df.get("Close"), errors="coerce"),
        },
        index=pd.to_datetime(df[date_col], errors="coerce"),
    ).dropna()
    return _ensure_ohlc(normalized)


def _download_market_fallback(ticker, interval, period):
    if interval != "1d":
        return None

    if ticker == "EURUSD=X":
        try:
            return _download_ecb_eurusd_history()
        except (requests.exceptions.RequestException, pd.errors.ParserError, ValueError, KeyError) as e:
            logger.warning("ECB EURUSD fallback hatasi ticker=%s err=%s", ticker, e)
            return None

    if ticker == "DX-Y.NYB":
        try:
            start_date = (datetime.now(LOCAL_TZ).date() - timedelta(days=365 * 3)).isoformat()
            return _download_fred_close_history("DTWEXBGS", start_date=start_date)
        except (requests.exceptions.RequestException, pd.errors.ParserError, ValueError, KeyError) as e:
            logger.warning("FRED DXY fallback hatasi ticker=%s err=%s", ticker, e)
        try:
            return _download_fred_data_history("DTWEXBGS")
        except (requests.exceptions.RequestException, pd.errors.ParserError, ValueError, KeyError) as e:
            logger.warning("FRED DXY data fallback hatasi ticker=%s err=%s", ticker, e)
            return None

    if ticker == "^VIX":
        try:
            return _download_cboe_vix_history()
        except (requests.exceptions.RequestException, pd.errors.ParserError, ValueError, KeyError) as e:
            logger.warning("CBOE VIX fallback hatasi ticker=%s err=%s", ticker, e)
            return None

    return None


def get_fmp_api_key():
    try:
        key = st.secrets.get("FMP_API_KEY", "")
        if key:
            return key
    except Exception:
        pass
    return os.getenv("FMP_API_KEY", "")


@st.cache_data(ttl=_TTL_SPOT, show_spinner=False)
def get_yahoo(ticker, interval="1d", period="6mo"):
    fetched_at = stamp(ticker)
    cache_key = f"yahoo_{ticker}_{interval}_{period}"
    needed = ["Open", "High", "Low", "Close"]

    for attempt in range(3):
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
                raise ValueError("bos dataframe")

            if isinstance(df.columns, pd.MultiIndex):
                df.columns = [c[0] for c in df.columns]

            for col in needed:
                if col not in df.columns:
                    raise KeyError(f"eksik kolon: {col}")

            df = df.dropna(subset=needed).copy()
            if df.empty:
                raise ValueError("temizleme sonrasi bos dataframe")

            _save_dataframe_cache(cache_key, df)
            return df, fetched_at
        except Exception as e:
            logger.warning(
                "get_yahoo: veri alinamadi ticker=%s interval=%s attempt=%s err=%s",
                ticker, interval, attempt + 1, e
            )
            if attempt < 2:
                time.sleep(1.5 * (attempt + 1))

    cached_df, cached_at = _load_dataframe_cache(cache_key)
    if cached_df is not None:
        logger.warning("get_yahoo: cache fallback kullanildi ticker=%s interval=%s", ticker, interval)
        return cached_df, cached_at

    fallback_df = _download_market_fallback(ticker, interval, period)
    if fallback_df is not None and not fallback_df.empty:
        logger.warning("get_yahoo: alternate source kullanildi ticker=%s interval=%s", ticker, interval)
        _save_dataframe_cache(cache_key, fallback_df)
        return fallback_df, stamp(f"{ticker}_alt")

    return None, fetched_at


@st.cache_data(ttl=_TTL_RATES, show_spinner=False)
def get_us2y_with_source():
    fetched_at = stamp("us2y")
    try:
        url = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS2"
        r = _http_get_with_retry(url)
        if r.status_code == 200 and r.text.strip():
            df = pd.read_csv(StringIO(r.text))
            if "DGS2" in df.columns:
                s = pd.to_numeric(df["DGS2"], errors="coerce").dropna()
                if not s.empty:
                    payload = {"value": float(s.iloc[-1]), "source": "FRED:DGS2", "status": "ok", "fetched_at": fetched_at.isoformat()}
                    _save_dict_cache("us2y", payload)
                    return {"value": float(s.iloc[-1]), "source": "FRED:DGS2", "status": "ok", "fetched_at": fetched_at}
    except (requests.exceptions.RequestException, pd.errors.ParserError, ValueError, KeyError) as e:
        logger.warning("get_us2y FRED: %s", e)

    try:
        url = (
            "https://home.treasury.gov/resource-center/data-chart-center/"
            "interest-rates/pages/xmlview?data=daily_treasury_yield_curve"
        )
        r = _http_get_with_retry(url)
        if r.status_code == 200 and r.text:
            matches = re.findall(r"BC_2YEAR[^0-9]*([\d\.]+)", r.text)
            if matches:
                payload = {"value": float(matches[-1]), "source": "USTREASURY:BC_2YEAR", "status": "ok", "fetched_at": fetched_at.isoformat()}
                _save_dict_cache("us2y", payload)
                return {"value": float(matches[-1]), "source": "USTREASURY:BC_2YEAR", "status": "ok", "fetched_at": fetched_at}
    except (requests.exceptions.RequestException, ValueError) as e:
        logger.warning("get_us2y Treasury: %s", e)

    try:
        table = _download_treasury_par_yield_table()
        if table is not None and not table.empty:
            series = pd.to_numeric(table["2 Yr"], errors="coerce").dropna()
            if not series.empty:
                value = float(series.iloc[-1])
                payload = {"value": value, "source": "USTREASURY:TEXTVIEW_2YR", "status": "ok", "fetched_at": fetched_at.isoformat()}
                _save_dict_cache("us2y", payload)
                return {"value": value, "source": "USTREASURY:TEXTVIEW_2YR", "status": "ok", "fetched_at": fetched_at}
    except (requests.exceptions.RequestException, ValueError, ImportError) as e:
        logger.warning("get_us2y Treasury TextView: %s", e)

    cached, cached_at = _load_dict_cache("us2y")
    if cached:
        logger.warning("get_us2y: cache fallback kullanildi")
        return {
            "value": safe_float(cached.get("value")),
            "source": cached.get("source"),
            "status": "stale-cache",
            "fetched_at": cached_at,
        }

    return {"value": None, "source": None, "status": "missing", "fetched_at": fetched_at}


@st.cache_data(ttl=_TTL_RATES, show_spinner=False)
def get_us10y_with_source():
    fetched_at = stamp("us10y")
    try:
        url = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10"
        r = _http_get_with_retry(url)
        if r.status_code == 200 and r.text.strip():
            df = pd.read_csv(StringIO(r.text))
            if "DGS10" in df.columns:
                s = pd.to_numeric(df["DGS10"], errors="coerce").dropna()
                if not s.empty:
                    payload = {"value": float(s.iloc[-1]), "source": "FRED:DGS10", "status": "ok", "fetched_at": fetched_at.isoformat()}
                    _save_dict_cache("us10y", payload)
                    return {"value": float(s.iloc[-1]), "source": "FRED:DGS10", "status": "ok", "fetched_at": fetched_at}
    except (requests.exceptions.RequestException, pd.errors.ParserError, ValueError, KeyError) as e:
        logger.warning("get_us10y FRED: %s", e)

    try:
        url = (
            "https://home.treasury.gov/resource-center/data-chart-center/"
            "interest-rates/pages/xmlview?data=daily_treasury_yield_curve"
        )
        r = _http_get_with_retry(url)
        if r.status_code == 200 and r.text:
            matches = re.findall(r"BC_10YEAR[^0-9]*([\d\.]+)", r.text)
            if matches:
                payload = {"value": float(matches[-1]), "source": "USTREASURY:BC_10YEAR", "status": "ok", "fetched_at": fetched_at.isoformat()}
                _save_dict_cache("us10y", payload)
                return {"value": float(matches[-1]), "source": "USTREASURY:BC_10YEAR", "status": "ok", "fetched_at": fetched_at}
    except (requests.exceptions.RequestException, ValueError) as e:
        logger.warning("get_us10y Treasury: %s", e)

    try:
        table = _download_treasury_par_yield_table()
        if table is not None and not table.empty:
            series = pd.to_numeric(table["10 Yr"], errors="coerce").dropna()
            if not series.empty:
                value = float(series.iloc[-1])
                payload = {"value": value, "source": "USTREASURY:TEXTVIEW_10YR", "status": "ok", "fetched_at": fetched_at.isoformat()}
                _save_dict_cache("us10y", payload)
                return {"value": value, "source": "USTREASURY:TEXTVIEW_10YR", "status": "ok", "fetched_at": fetched_at}
    except (requests.exceptions.RequestException, ValueError, ImportError) as e:
        logger.warning("get_us10y Treasury TextView: %s", e)

    cached, cached_at = _load_dict_cache("us10y")
    if cached:
        logger.warning("get_us10y: cache fallback kullanildi")
        return {
            "value": safe_float(cached.get("value")),
            "source": cached.get("source"),
            "status": "stale-cache",
            "fetched_at": cached_at,
        }

    return {"value": None, "source": None, "status": "missing", "fetched_at": fetched_at}


@st.cache_data(ttl=_TTL_RATES, show_spinner=False)
def get_de2y_with_source():
    fetched_at = stamp("de2y")
    try:
        url = "https://api.statistiken.bundesbank.de/rest/data/BBSSY/D.REN.EUR.A610.000000WT0202.A"
        r = _http_get_with_retry(url, params={"format": "sdmx_csv"})
        if r.status_code == 200 and r.text.strip():
            df = pd.read_csv(StringIO(r.text))
            obs_cols = [c for c in df.columns if c.upper() == "OBS_VALUE"]
            if not obs_cols:
                obs_cols = [c for c in df.columns if "OBS" in c.upper()]
            if obs_cols:
                s = pd.to_numeric(df[obs_cols[0]], errors="coerce").dropna()
                if not s.empty:
                    payload = {"value": float(s.iloc[-1]), "source": "BUNDESBANK:DE2Y", "status": "ok", "fetched_at": fetched_at.isoformat()}
                    _save_dict_cache("de2y", payload)
                    return {"value": float(s.iloc[-1]), "source": "BUNDESBANK:DE2Y", "status": "ok", "fetched_at": fetched_at}
    except (requests.exceptions.RequestException, pd.errors.ParserError, ValueError, KeyError) as e:
        logger.warning("get_de2y Bundesbank: %s", e)

    try:
        url = (
            "https://data-api.ecb.europa.eu/service/data/"
            "YC/B.U2.EUR.4F.G_N_A.SV_C_YM.SR_2Y"
        )
        r = _http_get_with_retry(url, params={"format": "csvdata"})
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
                    payload = {"value": float(s.iloc[-1]), "source": "ECB:DE2Y", "status": "ok", "fetched_at": fetched_at.isoformat()}
                    _save_dict_cache("de2y", payload)
                    return {"value": float(s.iloc[-1]), "source": "ECB:DE2Y", "status": "ok", "fetched_at": fetched_at}
    except (requests.exceptions.RequestException, pd.errors.ParserError, ValueError, KeyError) as e:
        logger.warning("get_de2y ECB: %s", e)

    cached, cached_at = _load_dict_cache("de2y")
    if cached:
        logger.warning("get_de2y: cache fallback kullanildi")
        return {
            "value": safe_float(cached.get("value")),
            "source": cached.get("source"),
            "status": "stale-cache",
            "fetched_at": cached_at,
        }

    return {"value": None, "source": None, "status": "missing", "fetched_at": fetched_at}


@st.cache_data(ttl=_TTL_RATES, show_spinner=False)
def get_de10y_with_source():
    fetched_at = stamp("de10y")
    try:
        url = (
            "https://data-api.ecb.europa.eu/service/data/"
            "YC/B.U2.EUR.4F.G_N_A.SV_C_YM.SR_10Y"
        )
        r = _http_get_with_retry(url, params={"format": "csvdata"})
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
                    payload = {"value": float(s.iloc[-1]), "source": "ECB:DE10Y", "status": "ok", "fetched_at": fetched_at.isoformat()}
                    _save_dict_cache("de10y", payload)
                    return {"value": float(s.iloc[-1]), "source": "ECB:DE10Y", "status": "ok", "fetched_at": fetched_at}
    except (requests.exceptions.RequestException, pd.errors.ParserError, ValueError, KeyError) as e:
        logger.warning("get_de10y ECB: %s", e)

    cached, cached_at = _load_dict_cache("de10y")
    if cached:
        logger.warning("get_de10y: cache fallback kullanildi")
        return {
            "value": safe_float(cached.get("value")),
            "source": cached.get("source"),
            "status": "stale-cache",
            "fetched_at": cached_at,
        }

    return {"value": None, "source": None, "status": "missing", "fetched_at": fetched_at}


def _is_high_impact(impact_value):
    if impact_value is None:
        return False
    text = str(impact_value).strip().lower()
    if text in {"high", "3", "3.0"}:
        return True
    try:
        return float(text) >= 3
    except ValueError:
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


@st.cache_data(ttl=_TTL_MACRO, show_spinner=False)
def get_macro_events_with_source():
    fetched_at = stamp("macro_events")
    api_key = get_fmp_api_key()
    if not api_key:
        cached, cached_at = _load_list_cache("macro_events")
        if cached:
            logger.warning("get_macro_events_with_source: api key yok, cache fallback kullanildi")
            return {"events": cached, "source": "FMP:EconomicCalendar", "status": "stale-cache", "fetched_at": cached_at}
        return {"events": [], "source": None, "status": "missing", "fetched_at": fetched_at}

    try:
        today = datetime.now(LOCAL_TZ).date()
        end_day = today + timedelta(days=7)

        url = "https://financialmodelingprep.com/api/v3/economic_calendar"
        params = {
            "from": today.isoformat(),
            "to": end_day.isoformat(),
            "apikey": api_key,
        }

        r = _http_get_with_retry(url, params=params)
        if r.status_code != 200:
            return {"events": [], "source": "FMP", "status": "missing", "fetched_at": fetched_at}

        data = r.json()
        if not isinstance(data, list):
            return {"events": [], "source": "FMP", "status": "missing", "fetched_at": fetched_at}

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
        if events:
            _save_list_cache("macro_events", events)
        return {"events": events, "source": "FMP:EconomicCalendar", "status": "ok" if events else "empty", "fetched_at": fetched_at}
    except (requests.exceptions.RequestException, ValueError, KeyError) as e:
        logger.warning("get_macro_events_with_source: FMP API hatası err=%s", e)
        cached, cached_at = _load_list_cache("macro_events")
        if cached:
            logger.warning("get_macro_events_with_source: cache fallback kullanildi")
            return {"events": cached, "source": "FMP:EconomicCalendar", "status": "stale-cache", "fetched_at": cached_at}
        return {"events": [], "source": "FMP:EconomicCalendar", "status": "missing", "fetched_at": fetched_at}


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


@st.cache_data(ttl=_TTL_SPOT, show_spinner=False)
def get_market_bundle():
    eur_1d, ts_eur_1d = get_yahoo("EURUSD=X", "1d", "10y")
    eur_4h, ts_eur_4h = get_yahoo("EURUSD=X", "4h", "180d")
    if eur_4h is None or eur_4h.empty:
        eur_1h, ts_eur_1h = get_yahoo("EURUSD=X", "1h", "60d")
        eur_4h_from_1h = _resample_to_4h(eur_1h)
        if eur_4h_from_1h is not None and not eur_4h_from_1h.empty:
            logger.warning("get_market_bundle: EURUSD 4H verisi 1H veriden uretildi")
            eur_4h = eur_4h_from_1h
            ts_eur_4h = ts_eur_1h
    dxy_df, ts_dxy    = get_yahoo("DX-Y.NYB", "1d", "10y")
    vix_df, ts_vix    = get_yahoo("^VIX", "1d", "10y")

    dxy_source_override = None
    if dxy_df is None or dxy_df.empty:
        dxy_proxy = _build_inverse_fx_proxy(eur_1d)
        if dxy_proxy is not None and not dxy_proxy.empty:
            logger.warning("get_market_bundle: DXY verisi EURUSD ters proxy ile uretildi")
            dxy_df = dxy_proxy
            ts_dxy = ts_eur_1d
            dxy_source_override = "PROXY:EURUSD_INVERSE"

    us2y_info  = get_us2y_with_source()
    us10y_info = get_us10y_with_source()
    de2y_info  = get_de2y_with_source()
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
        dxy_end   = safe_float(dxy_df["Close"].iloc[-1])
        dxy_pct = pct(dxy_start, dxy_end)

    vix_val = safe_float(vix_df["Close"].iloc[-1]) if vix_df is not None and not vix_df.empty else None

    checks = {
        "EURUSD_1D": eur_1d is not None and not eur_1d.empty,
        "EURUSD_4H": eur_4h is not None and not eur_4h.empty,
        "DXY":       dxy_df is not None and not dxy_df.empty,
        "VIX":       vix_df is not None and not vix_df.empty,
        "US2Y":      us2y_info["value"]  is not None,
        "US10Y":     us10y_info["value"] is not None,
        "DE2Y":      de2y_info["value"]  is not None,
        "DE10Y":     de10y_info["value"] is not None,
    }

    # Tazelik hesapla
    freshness = build_bundle_freshness({
        "eur_1d":       ts_eur_1d,
        "eur_4h":       ts_eur_4h,
        "dxy_df":       ts_dxy,
        "vix_df":       ts_vix,
        "us2y":         us2y_info.get("fetched_at"),
        "us10y":        us10y_info.get("fetched_at"),
        "de2y":         de2y_info.get("fetched_at"),
        "de10y":        de10y_info.get("fetched_at"),
        "macro_events": macro_info.get("fetched_at"),
    })

    bundle = {
        "eur_1d":      eur_1d,
        "eur_4h":      eur_4h,
        "dxy_df":      dxy_df,
        "vix_df":      vix_df,
        "spot":        spot,
        "support":     support,
        "resistance":  resistance,
        "dxy_pct":     dxy_pct,
        "vix":         vix_val,
        "us2y":        us2y_info["value"],
        "us10y":       us10y_info["value"],
        "de2y":        de2y_info["value"],
        "de10y":       de10y_info["value"],
        "us2y_source":  us2y_info["source"],
        "us10y_source": us10y_info["source"],
        "de2y_source":  de2y_info["source"],
        "de10y_source": de10y_info["source"],
        "dxy_source":   dxy_source_override or "YAHOO_OR_FRED",
        "macro_events": macro_info["events"],
        "macro_source": macro_info["source"],
        "macro_status": macro_info["status"],
        "data_quality": build_data_quality(checks),
        "freshness":    freshness,
    }

    return validate_market_bundle(bundle)
