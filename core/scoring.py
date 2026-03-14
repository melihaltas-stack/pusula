from datetime import datetime
from zoneinfo import ZoneInfo

from core.indicators import clamp, technical_snapshot, volatility_regime


LOCAL_TZ = ZoneInfo("Europe/Istanbul")


def _parse_event_dt(value):
    if not value:
        return None

    text = str(value).replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=LOCAL_TZ)
        return dt.astimezone(LOCAL_TZ)
    except Exception:
        return None


def score_dxy(dxy_pct):
    if dxy_pct is None:
        return 50, "DXY verisi yok"

    score = clamp(50 - (dxy_pct / 1.5) * 25, 0, 100)

    if dxy_pct <= -0.5:
        yorum = f"DXY zayıflıyor ({dxy_pct:.1f}%) → EUR lehine"
    elif dxy_pct >= 0.5:
        yorum = f"DXY güçleniyor (+{dxy_pct:.1f}%) → EUR baskı altında"
    else:
        yorum = f"DXY nötr ({dxy_pct:.1f}%)"

    return round(score, 1), yorum


def score_rates(us2y, de2y, us10y, de10y):
    parts = []

    if us2y is not None and de2y is not None:
        spread2 = us2y - de2y
        score2 = clamp(60 - (spread2 / 3.0) * 30, 0, 100)
        parts.append(score2)
        text2 = f"2Y spread: {spread2:.2f}%"
    else:
        text2 = "2Y spread yok"

    if us10y is not None and de10y is not None:
        spread10 = us10y - de10y
        score10 = clamp(60 - (spread10 / 3.5) * 30, 0, 100)
        parts.append(score10)
        text10 = f"10Y spread: {spread10:.2f}%"
    else:
        text10 = "10Y spread yok"

    if not parts:
        return 50, "Faiz verileri alınamadı"

    score = sum(parts) / len(parts)
    yorum = f"{text2} | {text10}"
    return round(score, 1), yorum


def score_vix(vix):
    if vix is None:
        return 50, "VIX verisi yok"

    score = clamp(70 - (vix - 12) * 2, 0, 100)

    if vix < 18:
        yorum = f"VIX: {vix:.1f} → Risk iştahı yüksek"
    elif vix > 25:
        yorum = f"VIX: {vix:.1f} → Risk iştahı düşük"
    else:
        yorum = f"VIX: {vix:.1f} → Normal volatilite"

    return round(score, 1), yorum


def score_technical(df):
    snap = technical_snapshot(df)
    if not snap.get("ok"):
        return 50, snap.get("reason", "Teknik veri yetersiz")

    ma20 = snap["ma20"]
    ma50 = snap["ma50"]
    rsi_val = snap["rsi"]
    macd_hist_val = snap["macd_hist"]
    last_close = snap["close"]

    trend_score = 65 if ma20 > ma50 else 35
    rsi_score = clamp(50 + (rsi_val - 50) * 1.2, 0, 100)
    macd_norm = (macd_hist_val / last_close) * 10000 if last_close else 0
    macd_score = clamp(50 + macd_norm * 8, 0, 100)

    score = clamp(
        0.45 * trend_score +
        0.30 * rsi_score +
        0.25 * macd_score,
        0, 100
    )

    yorum = (
        f"MA20/50: {snap['trend']} | "
        f"RSI: {rsi_val:.0f} ({snap['rsi_label']}) | "
        f"MACD Hist: {macd_hist_val:.5f}"
    )

    return round(score, 1), yorum


def score_form(spot, support, resistance):
    if spot is None or support is None or resistance is None:
        return 50, "Formasyon hesaplanamadı"

    if resistance <= support:
        return 50, "Formasyon hesaplanamadı"

    pos = (spot - support) / (resistance - support)
    pos = clamp(pos, 0, 1)

    score = clamp(40 + pos * 40, 0, 100)

    yorum = (
        f"Fiyat aralık içinde %{pos * 100:.0f} konumunda | "
        f"Destek: {support:.4f} | Direnç: {resistance:.4f}"
    )

    return round(score, 1), yorum


def score_volatility(df):
    vol = volatility_regime(df)
    if not vol.get("ok"):
        return 50, "Volatilite verisi yetersiz"

    atr_pct = vol.get("atr_pct")
    label = vol.get("label", "Bilinmiyor")

    if atr_pct is None:
        return 50, "Volatilite verisi yetersiz"

    if atr_pct < 0.45:
        score = 52
    elif atr_pct < 0.90:
        score = 60
    else:
        score = 45

    yorum = f"{label} | ATR: %{atr_pct:.2f}"
    return round(score, 1), yorum


def score_macro_risk(events):
    if not events:
        return 50, "Makro takvim verisi yok"

    now = datetime.now(LOCAL_TZ)
    upcoming = []

    for event in events:
        dt = _parse_event_dt(event.get("date"))
        if dt is None:
            continue
        hours = (dt - now).total_seconds() / 3600
        if hours >= -2:
            upcoming.append((hours, event))

    if not upcoming:
        return 65, "Yakın yüksek etkili veri yok"

    upcoming.sort(key=lambda x: x[0])
    hours_to_next, next_event = upcoming[0]

    event_name = next_event.get("event", "Yüksek etkili veri")
    country = next_event.get("country", "")
    dt = _parse_event_dt(next_event.get("date"))
    dt_txt = dt.strftime("%d.%m %H:%M") if dt else "Bilinmiyor"

    if hours_to_next <= 6:
        score = 20
    elif hours_to_next <= 12:
        score = 30
    elif hours_to_next <= 24:
        score = 40
    elif hours_to_next <= 48:
        score = 52
    elif hours_to_next <= 72:
        score = 58
    else:
        score = 65

    yorum = f"Yakın veri: {event_name} ({country}) | {dt_txt}"
    return round(score, 1), yorum


def score_positioning(cot_positioning):
    if not cot_positioning or cot_positioning.get("net_pct_open_interest") is None:
        return 50, "COT positioning verisi yok"

    net_pct_oi = float(cot_positioning.get("net_pct_open_interest", 0.0))
    weekly_change = cot_positioning.get("weekly_change_contracts")

    score = clamp(50 + net_pct_oi * 2.2, 0, 100)

    if weekly_change is not None:
        score = clamp(score + clamp(float(weekly_change) / 12000, -8, 8), 0, 100)

    if net_pct_oi >= 8:
        yorum = f"COT kalabalık EUR long (%{net_pct_oi:.1f} OI) → satış lehine"
    elif net_pct_oi <= -5:
        yorum = f"COT EUR short (%{net_pct_oi:.1f} OI) → squeeze riski"
    else:
        yorum = f"COT nötr/ılımlı (%{net_pct_oi:.1f} OI)"

    if weekly_change is not None:
        yorum += f" | Haftalık net değişim: {int(weekly_change):+d}"

    return round(score, 1), yorum


def score_spread_momentum(spread_momentum_5):
    if spread_momentum_5 is None:
        return 50, "Spread momentumu yok"

    score = clamp(50 - spread_momentum_5 * 1.8, 0, 100)
    if spread_momentum_5 >= 1.0:
        yorum = f"US-DE 2Y spread açılıyor ({spread_momentum_5:+.2f}%) → EUR baskısı"
    elif spread_momentum_5 <= -1.0:
        yorum = f"US-DE 2Y spread daralıyor ({spread_momentum_5:+.2f}%) → EUR destekli"
    else:
        yorum = f"US-DE 2Y spread momentumu nötr ({spread_momentum_5:+.2f}%)"
    return round(score, 1), yorum


def score_cross_asset(cross_asset):
    if not cross_asset:
        return 50, "Cross-asset verisi yok"

    spx_ret = cross_asset.get("spx_ret_5")
    eurostoxx_ret = cross_asset.get("eurostoxx_ret_5")
    gold_ret = cross_asset.get("gold_ret_5")
    oil_ret = cross_asset.get("oil_ret_5")
    equity_rel = cross_asset.get("equity_rel_5")

    parts = []
    score = 50.0

    if spx_ret is not None:
        score += clamp(-spx_ret * 1.3, -8, 8)
        parts.append(f"S&P {spx_ret:+.2f}%")
    if gold_ret is not None:
        score += clamp(gold_ret * 0.9, -6, 6)
        parts.append(f"Gold {gold_ret:+.2f}%")
    if oil_ret is not None:
        score += clamp(-oil_ret * 0.5, -4, 4)
        parts.append(f"Oil {oil_ret:+.2f}%")
    if equity_rel is not None:
        score += clamp(-equity_rel * 0.8, -5, 5)
        parts.append(f"EU rel {equity_rel:+.2f}%")
    elif eurostoxx_ret is not None:
        parts.append(f"EuroStoxx {eurostoxx_ret:+.2f}%")

    if not parts:
        return 50, "Cross-asset verisi yok"

    if score >= 58:
        yorum = f"Risk modu EUR satışı destekliyor | {' | '.join(parts)}"
    elif score <= 42:
        yorum = f"Risk modu EUR lehine | {' | '.join(parts)}"
    else:
        yorum = f"Cross-asset görünüm karışık | {' | '.join(parts)}"

    return round(clamp(score, 0, 100), 1), yorum


def score_data_quality(data_quality):
    if not data_quality:
        return 50, "Veri kalite bilgisi yok"

    score = data_quality.get("score", 0)
    label = data_quality.get("label", "Bilinmiyor")
    missing = data_quality.get("missing", [])

    if not missing:
        yorum = f"Veri güveni: {label} ({score:.0f}/100)"
    else:
        yorum = f"Veri güveni: {label} ({score:.0f}/100) | Eksik: {', '.join(missing)}"

    return round(score, 1), yorum


def score_momentum(df):
    """Momentum alt skoru: 5G ve 20G yüzde değişimden türetilir.

    Yüksek pozitif momentum → EUR güçlü → düşük satış önceliği (düşük skor)
    Yüksek negatif momentum → EUR zayıf → yüksek satış önceliği (yüksek skor)
    """
    from core.indicators import momentum_pct

    if df is None or df.empty or len(df) < 25:
        return 50, "Momentum verisi yetersiz"

    close = df["Close"]
    mom_5 = momentum_pct(close, 5)
    mom_20 = momentum_pct(close, 20)

    if mom_5 is None and mom_20 is None:
        return 50, "Momentum hesaplanamadı"

    # 5 günlük momentum ağırlıklı
    score_5 = 50.0
    if mom_5 is not None:
        # Negatif momentum → yüksek skor (satış fırsatı)
        score_5 = clamp(50 - mom_5 * 20, 0, 100)

    score_20 = 50.0
    if mom_20 is not None:
        score_20 = clamp(50 - mom_20 * 10, 0, 100)

    # 5G ağırlığı %65, 20G ağırlığı %35
    score = score_5 * 0.65 + score_20 * 0.35

    parts = []
    if mom_5 is not None:
        parts.append(f"5G: {mom_5:+.2f}%")
    if mom_20 is not None:
        parts.append(f"20G: {mom_20:+.2f}%")

    if score >= 65:
        yorum = f"Negatif momentum ({', '.join(parts)}) → Satış fırsatı"
    elif score <= 35:
        yorum = f"Pozitif momentum ({', '.join(parts)}) → EUR güçlü"
    else:
        yorum = f"Nötr momentum ({', '.join(parts)})"

    return round(clamp(score, 0, 100), 1), yorum


def build_scores(bundle):
    dxy_score, dxy_comment = score_dxy(bundle.get("dxy_pct"))
    if bundle.get("dxy_source") == "PROXY:EURUSD_INVERSE":
        dxy_comment = f"{dxy_comment} | Proxy kaynak: EUR/USD ters seri"
    rate_score, rate_comment = score_rates(
        bundle.get("us2y"),
        bundle.get("de2y"),
        bundle.get("us10y"),
        bundle.get("de10y"),
    )
    risk_score, risk_comment = score_vix(bundle.get("vix"))
    tech_score, tech_comment = score_technical(bundle.get("eur_1d"))
    form_score, form_comment = score_form(
        bundle.get("spot"),
        bundle.get("support"),
        bundle.get("resistance"),
    )
    vol_score, vol_comment = score_volatility(bundle.get("eur_1d"))
    macro_score, macro_comment = score_macro_risk(bundle.get("macro_events"))
    dq_score, dq_comment = score_data_quality(bundle.get("data_quality"))
    mom_score, mom_comment = score_momentum(bundle.get("eur_1d"))
    positioning_score, positioning_comment = score_positioning(bundle.get("cot_positioning"))
    spread_mom_score, spread_mom_comment = score_spread_momentum(bundle.get("spread_2y_momentum_5"))
    cross_asset_score, cross_asset_comment = score_cross_asset(bundle.get("cross_asset"))

    scores = {
        "DXY": dxy_score,
        "Faiz": rate_score,
        "Risk": risk_score,
        "Teknik": tech_score,
        "Form": form_score,
        "Volatilite": vol_score,
        "MacroRisk": macro_score,
        "VeriGüveni": dq_score,
        "Momentum": mom_score,
        "Positioning": positioning_score,
        "SpreadMomentum": spread_mom_score,
        "CrossAsset": cross_asset_score,
    }

    comments = {
        "DXY": dxy_comment,
        "Faiz": rate_comment,
        "Risk": risk_comment,
        "Teknik": tech_comment,
        "Form": form_comment,
        "Volatilite": vol_comment,
        "MacroRisk": macro_comment,
        "VeriGüveni": dq_comment,
        "Momentum": mom_comment,
        "Positioning": positioning_comment,
        "SpreadMomentum": spread_mom_comment,
        "CrossAsset": cross_asset_comment,
    }

    return scores, comments
