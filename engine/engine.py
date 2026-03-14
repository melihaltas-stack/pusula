from datetime import datetime
from zoneinfo import ZoneInfo
import logging

logger = logging.getLogger(__name__)
from core.data_sources import get_market_bundle
from core.indicators import technical_snapshot, detect_trend_regime, timeframe_snapshot
from core.scoring import build_scores
from planner.planner import build_sale_plan
from backtest.backtest import build_probability_summary


LOCAL_TZ = ZoneInfo("Europe/Istanbul")


def fmt_num(value, digits=2, suffix=""):
    if value is None:
        return "N/A"
    return f"{value:.{digits}f}{suffix}"


def fmt_signed_pct(value):
    if value is None:
        return "Hesaplanamadı"
    return f"{value:+.2f}%"


def classify_decision(ede_score):
    if ede_score >= 65:
        return {"karar": "Güçlü satış penceresi", "renk": "sat", "emoji": "🟢"}
    elif ede_score >= 52:
        return {"karar": "Kademeli satış uygun", "renk": "hazirlan", "emoji": "🟡"}
    elif ede_score >= 40:
        return {"karar": "Hazırlan", "renk": "hazirlan", "emoji": "🟠"}
    else:
        return {"karar": "Bekle", "renk": "bekle", "emoji": "🔵"}


def classify_confidence(data_quality_score):
    if data_quality_score >= 90:
        return "Yüksek"
    elif data_quality_score >= 65:
        return "Orta"
    return "Düşük"


HORIZON_META = {
    "short_term": {"label": "Kısa Vade", "window": "1-5 gün"},
    "medium_term": {"label": "Orta Vade", "window": "1-3 hafta"},
    "long_term": {"label": "Uzun Vade", "window": "4+ hafta"},
}


def build_weights(horizon="medium_term", dxy_source=None):
    horizon_weights = {
        "short_term": {
            "DXY": 0.14,
            "Faiz": 0.06,
            "Risk": 0.14,
            "Teknik": 0.20,
            "Form": 0.08,
            "Volatilite": 0.08,
            "MacroRisk": 0.06,
            "Momentum": 0.24,
        },
        "medium_term": {
            "DXY": 0.17,
            "Faiz": 0.16,
            "Risk": 0.12,
            "Teknik": 0.18,
            "Form": 0.10,
            "Volatilite": 0.07,
            "MacroRisk": 0.07,
            "Momentum": 0.13,
        },
        "long_term": {
            "DXY": 0.12,
            "Faiz": 0.20,
            "Risk": 0.08,
            "Teknik": 0.12,
            "Form": 0.18,
            "Volatilite": 0.05,
            "MacroRisk": 0.10,
            "Momentum": 0.15,
        },
    }

    weights = horizon_weights.get(horizon, horizon_weights["medium_term"]).copy()

    if dxy_source == "PROXY:EURUSD_INVERSE":
        # Proxy DXY yön hissi verir ama gerçek endeks kadar güvenilir değildir.
        lost = weights["DXY"] - 0.06
        weights["DXY"] = 0.06
        weights["Risk"] += lost * 0.35
        weights["Teknik"] += lost * 0.35
        weights["Momentum"] += lost * 0.30

    return weights


def calculate_ede(scores, horizon="medium_term", dxy_source=None, trend_regime=None):
    weights = build_weights(horizon=horizon, dxy_source=dxy_source)
    ede = 0.0
    for key, weight in weights.items():
        ede += scores.get(key, 50) * weight
    if trend_regime == "DOWN":
        if horizon == "short_term":
            ede += 8
        elif horizon == "medium_term":
            ede += 4
    elif trend_regime == "UP":
        if horizon == "short_term":
            ede -= 8
        elif horizon == "medium_term":
            ede -= 4
    return round(ede, 1)


def classify_horizon_decision(ede_score, horizon="medium_term"):
    thresholds = {
        "short_term": (58, 48, 38),
        "medium_term": (65, 52, 40),
        "long_term": (68, 55, 43),
    }
    strong, ready, prep = thresholds.get(horizon, thresholds["medium_term"])
    if ede_score >= strong:
        return {"karar": "Güçlü satış penceresi", "renk": "sat", "emoji": "🟢"}
    if ede_score >= ready:
        return {"karar": "Kademeli satış uygun", "renk": "hazirlan", "emoji": "🟡"}
    if ede_score >= prep:
        return {"karar": "Hazırlan", "renk": "hazirlan", "emoji": "🟠"}
    return {"karar": "Bekle", "renk": "bekle", "emoji": "🔵"}


def build_spread(us, de):
    if us is None or de is None:
        return None
    return us - de


def build_next_macro_event_text(events):
    if not events:
        return "Yakın yüksek etkili veri bulunamadı"

    now = datetime.now(LOCAL_TZ)
    candidates = []

    for event in events:
        date_raw = event.get("date")
        if not date_raw:
            continue

        try:
            dt = datetime.fromisoformat(str(date_raw).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=LOCAL_TZ)
            dt = dt.astimezone(LOCAL_TZ)
        except (ValueError, AttributeError, OSError) as e:
            logger.debug("build_next_macro_event_text: tarih parse hatası event=%r err=%s", event, e)
            continue

        hours = (dt - now).total_seconds() / 3600
        if hours >= -2:
            candidates.append((dt, event))

    if not candidates:
        return "Yakın yüksek etkili veri bulunamadı"

    candidates.sort(key=lambda x: x[0])
    dt, event = candidates[0]

    event_name = event.get("event", "Yüksek etkili veri")
    country = event.get("country", "")
    return f"{dt.strftime('%d.%m %H:%M')} | {event_name} ({country})"


def build_risk_note(d):
    if d["scores"]["MacroRisk"] < 35:
        return "En büyük risk: yakın yüksek etkili makro veri."
    if d["confidence_label"] == "Düşük":
        return "En büyük risk: veri güveni düşük."
    if d["trend_regime"] == "UP" and d["sale_plan"]["daily_units"] >= 40:
        return "En büyük risk: yukarı trend devam ederse erken satış hissi oluşabilir."
    return "En büyük risk: piyasa yönünün veri sonrası hızla değişmesi."


def build_operation_summary(d):
    return (
        f"Bugün EUR satış ortamı {d['karar'].lower()}. "
        f"EDE {d['ede']}. Veri güveni {d['confidence_label'].lower()}. "
        f"Toplam {d['sale_plan']['daily_units']} birim satış önerilir; "
        f"{d['sale_plan']['morning_units']} birim sabah, "
        f"{d['sale_plan']['afternoon_units']} birim öğleden sonra uygulanabilir."
    )


def build_horizon_view(horizon, scores, dxy_source, trend_regime, macro_score):
    meta = HORIZON_META[horizon]
    ede = calculate_ede(scores, horizon=horizon, dxy_source=dxy_source, trend_regime=trend_regime)
    decision = classify_horizon_decision(ede, horizon=horizon)
    sale_plan = build_sale_plan(ede, trend_regime, macro_score, horizon=horizon)
    sorted_weights = sorted(build_weights(horizon=horizon, dxy_source=dxy_source).items(), key=lambda x: x[1], reverse=True)
    focus = ", ".join(name for name, _ in sorted_weights[:3])
    summary = f"{meta['label']} ({meta['window']}) icin ana odak: {focus}."
    return {
        "key": horizon,
        "label": meta["label"],
        "window": meta["window"],
        "ede": ede,
        "karar": decision["karar"],
        "renk": decision["renk"],
        "emoji": decision["emoji"],
        "sale_plan": sale_plan,
        "weights": build_weights(horizon=horizon, dxy_source=dxy_source),
        "summary": summary,
    }


formula_box_text = """
### 🧠 Bu skor nasıl hesaplanıyor?

Bu sistem tek bir göstergeye bakmaz. EUR/USD için önemli olan birkaç farklı alan birlikte incelenir:

- **DXY** → Dolar genel olarak güçleniyor mu zayıflıyor mu?
- **Faiz farkı** → ABD ve Almanya tahvil faiz farkları EUR/USD üzerinde baskı kuruyor mu?
- **Risk algısı** → VIX ile piyasanın sakin mi gergin mi olduğu ölçülür.
- **Teknik görünüm** → Trend, RSI ve MACD ile fiyatın yönü ve gücü analiz edilir.
- **Formasyon** → Fiyat son dönemde destek mi direnç mi tarafına yakın?
- **Volatilite** → Piyasa çok sakin mi yoksa aşırı hareketli mi?
- **Makro risk** → ECB, FED, CPI, NFP gibi yüksek etkili veri ve konuşmalar yakın mı?

Her başlık **0-100 arasında puanlanır**. Sonra bu puanların ağırlıklı ortalaması alınır ve **EDE skoru** oluşur.

- Yüksek skor → EUR satışı için daha uygun ortam
- Düşük skor → Beklemek için daha mantıklı ortam

Sistem ayrıca **veri güven skoru** üretir ve benzer tarihsel koşullara göre olasılık özeti sunar.
"""


def run_engine(manual_inputs=None):
    bundle = get_market_bundle(manual_inputs=manual_inputs)

    eur_1d = bundle.get("eur_1d")
    if eur_1d is None or eur_1d.empty:
        return {
            "error": "EUR/USD verisi alınamadı. Lütfen biraz sonra tekrar deneyin.",
            "freshness": bundle.get("freshness"),
            "data_quality": bundle.get("data_quality"),
            "validation_flags": bundle.get("validation_flags", []),
            "validation_summary": bundle.get("validation_summary", {}),
        }

    scores, comments = build_scores(bundle)
    trend_regime = detect_trend_regime(eur_1d)
    horizon_views = {
        key: build_horizon_view(
            key,
            scores,
            bundle.get("dxy_source"),
            trend_regime,
            scores.get("MacroRisk", 50),
        )
        for key in ["short_term", "medium_term", "long_term"]
    }
    primary_horizon = horizon_views["short_term"]
    ede = primary_horizon["ede"]
    decision = {
        "karar": primary_horizon["karar"],
        "renk": primary_horizon["renk"],
        "emoji": primary_horizon["emoji"],
    }

    data_quality = bundle.get("data_quality", {})
    data_quality_score = data_quality.get("score", 0)
    confidence_label = classify_confidence(data_quality_score)

    sale_plan = primary_horizon["sale_plan"]

    technical = technical_snapshot(eur_1d)
    tf_daily = timeframe_snapshot(eur_1d, min_len=100)
    tf_4h = timeframe_snapshot(bundle.get("eur_4h"), min_len=60)

    probability = build_probability_summary(
        bundle.get("eur_1d"),
        bundle.get("dxy_df"),
        bundle.get("vix_df"),
        ede,
        trend_regime,
    )

    next_macro_event = build_next_macro_event_text(bundle.get("macro_events", []))
    spread_2y = build_spread(bundle.get("us2y"), bundle.get("de2y"))
    spread_10y = build_spread(bundle.get("us10y"), bundle.get("de10y"))

    now_str = datetime.now(LOCAL_TZ).strftime("%d.%m.%Y %H:%M")

    result = {
        "error": None,
        "zaman": now_str,
        "spot": bundle.get("spot"),
        "support": bundle.get("support"),
        "resistance": bundle.get("resistance"),
        "dxy_pct": bundle.get("dxy_pct"),
        "dxy_source": bundle.get("dxy_source"),
        "manual_mode": bundle.get("manual_mode", False),
        "active_horizon": primary_horizon["key"],
        "active_horizon_label": primary_horizon["label"],
        "weights": primary_horizon["weights"],
        "vix": bundle.get("vix"),
        "us2y": bundle.get("us2y"),
        "us10y": bundle.get("us10y"),
        "de2y": bundle.get("de2y"),
        "de10y": bundle.get("de10y"),
        "spread_2y": spread_2y,
        "spread_10y": spread_10y,
        "us2y_source": bundle.get("us2y_source"),
        "us10y_source": bundle.get("us10y_source"),
        "de2y_source": bundle.get("de2y_source"),
        "de10y_source": bundle.get("de10y_source"),
        "macro_source": bundle.get("macro_source"),
        "macro_status": bundle.get("macro_status"),
        "macro_events": bundle.get("macro_events", []),
        "next_macro_event": next_macro_event,
        "eur_1d": bundle.get("eur_1d"),
        "eur_4h": bundle.get("eur_4h"),
        "dxy_df": bundle.get("dxy_df"),
        "vix_df": bundle.get("vix_df"),
        "scores": scores,
        "yorumlar": comments,
        "ede": ede,
        "karar": decision["karar"],
        "renk": decision["renk"],
        "emoji": decision["emoji"],
        "data_quality": data_quality,
        "data_quality_score": data_quality_score,
        "confidence_label": confidence_label,
        "trend_regime": trend_regime,
        "technical": technical,
        "tf_daily": tf_daily,
        "tf_4h": tf_4h,
        "sale_plan": sale_plan,
        "horizon_views": horizon_views,
        "probability": probability,
        "formula_box_text": formula_box_text,
        "freshness": bundle.get("freshness"),
        "validation_flags": bundle.get("validation_flags", []),
        "validation_summary": bundle.get("validation_summary", {}),
        "validation_results": bundle.get("validation_results", {}),
    }

    result["risk_note"] = build_risk_note(result)
    result["operation_summary"] = build_operation_summary(result)
    result["debug"] = {
        "sources": {
            "us2y_source": result["us2y_source"],
            "us10y_source": result["us10y_source"],
            "de2y_source": result["de2y_source"],
            "de10y_source": result["de10y_source"],
            "dxy_source": result["dxy_source"],
            "macro_source": result["macro_source"],
        },
        "scores": scores,
        "weights": result["weights"],
        "comments": comments,
        "data_quality": data_quality,
        "trend_regime": trend_regime,
        "probability": probability,
        "validation_summary": bundle.get("validation_summary", {}),
        "validation_flags": bundle.get("validation_flags", []),
        "freshness_summary": bundle["freshness"].summary_text if bundle.get("freshness") else "N/A",
    }

    return result


def build_report_text(d):
    return f"""
**📅 {d['zaman']} | Selvese EUR Satış Pusulası**

---

**📍 Piyasa Durumu**
- EUR/USD Spot: **{fmt_num(d['spot'], 4)}**
- DXY 3 günlük değişim: **{fmt_signed_pct(d['dxy_pct'])}**
- VIX: **{fmt_num(d['vix'], 1)}**
- ABD 2Y / Almanya 2Y Spread: **{fmt_num(d['spread_2y'], 2, '%')}**
- ABD 10Y / Almanya 10Y Spread: **{fmt_num(d['spread_10y'], 2, '%')}**
- Trend rejimi: **{d['trend_regime']}**
- Sonraki önemli makro olay: **{d['next_macro_event']}**
- Veri Güveni: **{d['confidence_label']}** ({fmt_num(d['data_quality_score'], 0)}/100)

---

**📊 Skor Detayları**
| Kategori | Skor | Yorum |
|----------|------|-------|
| DXY | {d['scores']['DXY']:.0f} | {d['yorumlar']['DXY']} |
| Faiz | {d['scores']['Faiz']:.0f} | {d['yorumlar']['Faiz']} |
| Risk | {d['scores']['Risk']:.0f} | {d['yorumlar']['Risk']} |
| Teknik | {d['scores']['Teknik']:.0f} | {d['yorumlar']['Teknik']} |
| Formasyon | {d['scores']['Form']:.0f} | {d['yorumlar']['Form']} |
| Volatilite | {d['scores']['Volatilite']:.0f} | {d['yorumlar']['Volatilite']} |
| Makro Risk | {d['scores']['MacroRisk']:.0f} | {d['yorumlar']['MacroRisk']} |
| Veri Güveni | {d['scores']['VeriGüveni']:.0f} | {d['yorumlar']['VeriGüveni']} |

---

**🧭 EDE Skoru: {d['ede']} / 100 → {d['emoji']} {d['karar']}**

**Bugünün satış planı**
- Toplam satış: **{d['sale_plan']['daily_units']} / 100 birim**
- Sabah: **{d['sale_plan']['morning_units']} birim**
- Öğleden sonra: **{d['sale_plan']['afternoon_units']} birim**

**Operasyon özeti**
{d['operation_summary']}

**En büyük risk**
{d['risk_note']}

**Olasılık özeti**
{d['probability']['summary_text']}
"""
