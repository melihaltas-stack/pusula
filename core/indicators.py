import pandas as pd


def safe_float(x):
    try:
        if pd.isna(x):
            return None
        return float(x)
    except (TypeError, ValueError):
        return None


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


def ema(series, span):
    return series.ewm(span=span, adjust=False).mean()


def sma(series, window):
    return series.rolling(window).mean()


def rsi(close, period=14):
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)

    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()

    rs = avg_gain / avg_loss.replace(0, pd.NA)
    return 100 - (100 / (1 + rs))


def macd(close, fast=12, slow=26, signal=9):
    macd_line = ema(close, fast) - ema(close, slow)
    signal_line = ema(macd_line, signal)
    hist = macd_line - signal_line

    return {
        "macd": macd_line,
        "signal": signal_line,
        "hist": hist,
    }


def macd_hist(close):
    return macd(close)["hist"]


def true_range(df):
    high = df["High"]
    low = df["Low"]
    close = df["Close"]
    prev_close = close.shift(1)

    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()

    return pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)


def atr(df, period=14):
    tr = true_range(df)
    return tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def momentum_pct(close, lookback=5):
    if close is None or len(close) <= lookback:
        return None

    start = safe_float(close.iloc[-(lookback + 1)])
    end = safe_float(close.iloc[-1])

    if start is None or end is None or start == 0:
        return None

    return (end / start - 1) * 100


def trend_label(ma_fast, ma_slow):
    if ma_fast is None or ma_slow is None:
        return "Bilinmiyor"
    return "Yukarı trend" if ma_fast > ma_slow else "Aşağı trend"


def rsi_label(rsi_value):
    if rsi_value is None:
        return "Bilinmiyor"
    if rsi_value > 70:
        return "Aşırı alım"
    if rsi_value < 30:
        return "Aşırı satım"
    return "Normal"


def detect_trend_regime(df):
    if df is None or df.empty or len(df) < 120:
        return "SIDEWAYS"

    close = df["Close"]
    ma20 = safe_float(sma(close, 20).iloc[-1])
    ma50 = safe_float(sma(close, 50).iloc[-1])
    ma100 = safe_float(sma(close, 100).iloc[-1])

    if None in (ma20, ma50, ma100):
        return "SIDEWAYS"

    if ma20 > ma50 > ma100:
        return "UP"
    if ma20 < ma50 < ma100:
        return "DOWN"
    return "SIDEWAYS"


def technical_snapshot(df):
    if df is None or df.empty or len(df) < 100:
        return {"ok": False, "reason": "Teknik veri yetersiz"}

    close = df["Close"].copy()

    ma20 = safe_float(sma(close, 20).iloc[-1])
    ma50 = safe_float(sma(close, 50).iloc[-1])
    ma100 = safe_float(sma(close, 100).iloc[-1])

    rsi_val = safe_float(rsi(close).iloc[-1])
    macd_hist_val = safe_float(macd_hist(close).iloc[-1])

    atr_val = safe_float(atr(df, 14).iloc[-1])
    last_close = safe_float(close.iloc[-1])

    atr_pct = None
    if atr_val is not None and last_close not in (None, 0):
        atr_pct = (atr_val / last_close) * 100

    mom_5 = momentum_pct(close, 5)
    mom_20 = momentum_pct(close, 20)

    trend = trend_label(ma20, ma50)
    regime = detect_trend_regime(df)
    rsi_text = rsi_label(rsi_val)

    if None in (ma20, ma50, ma100, rsi_val, macd_hist_val, last_close):
        return {"ok": False, "reason": "Teknik hesaplama eksik"}

    return {
        "ok": True,
        "close": last_close,
        "ma20": ma20,
        "ma50": ma50,
        "ma100": ma100,
        "rsi": rsi_val,
        "rsi_label": rsi_text,
        "macd_hist": macd_hist_val,
        "atr": atr_val,
        "atr_pct": atr_pct,
        "mom_5": mom_5,
        "mom_20": mom_20,
        "trend": trend,
        "regime": regime,
    }


def volatility_regime(df):
    snap = technical_snapshot(df)
    if not snap.get("ok"):
        return {"ok": False, "label": "Bilinmiyor", "atr_pct": None}

    atr_pct = snap.get("atr_pct")
    if atr_pct is None:
        return {"ok": False, "label": "Bilinmiyor", "atr_pct": None}

    if atr_pct < 0.45:
        label = "Düşük volatilite"
    elif atr_pct < 0.90:
        label = "Normal volatilite"
    else:
        label = "Yüksek volatilite"

    return {"ok": True, "label": label, "atr_pct": atr_pct}


def timeframe_snapshot(df, min_len=60):
    if df is None or df.empty or len(df) < min_len:
        return {"ok": False, "reason": "Veri yetersiz"}

    close = df["Close"].copy()

    ma20 = safe_float(sma(close, 20).iloc[-1]) if len(close) >= 20 else None
    ma50 = safe_float(sma(close, 50).iloc[-1]) if len(close) >= 50 else None
    rsi_val = safe_float(rsi(close).iloc[-1]) if len(close) >= 15 else None
    macd_hist_val = safe_float(macd_hist(close).iloc[-1]) if len(close) >= 35 else None
    mom_5 = momentum_pct(close, 5) if len(close) >= 6 else None

    return {
        "ok": True,
        "close": safe_float(close.iloc[-1]),
        "ma20": ma20,
        "ma50": ma50,
        "rsi": rsi_val,
        "rsi_label": rsi_label(rsi_val),
        "macd_hist": macd_hist_val,
        "momentum_5": mom_5,
        "trend": trend_label(ma20, ma50),
    }