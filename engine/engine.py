from datetime import datetime
from zoneinfo import ZoneInfo

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


def build_weights():
    return {
        "DXY": 0.22,
        "Faiz": 0.18,
        "Risk": 0.12,
        "Teknik": 0.22,
        "Form": 0.12,
        "Volatilite": 0.07,
        "MacroRisk": 0.07,
    }


def calculate_ede(scores):
    weights = build_weights()
    ede = 0.0
    for key, weight in weights.items():
        ede += scores.get(key, 50) * weight
    return round(ede, 1)


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
        except Exception:
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




def build_forecast(probability, ede, trend_regime):
    """
    Mevcut backtest/probability verisini kullanarak
    app.py'nin beklediği forecast dict'ini üretir.
    """
    if not probability or probability.get("sample_size", 0) == 0:
        return None

    horizons_raw = probability.get("horizons", {})
    if not horizons_raw:
        return None

    horizons = {}
    for h, data in horizons_raw.items():
        down_prob = data.get("down_probability", 50.0)
        avg_ret = data.get("avg_return", 0.0)

        # Yön tahmini
        if down_prob >= 55:
            direction = "DOWN"
            emoji = "🔴"
            probability_val = down_prob
        elif down_prob <= 45:
            direction = "UP"
            emoji = "🟢"
            probability_val = 100 - down_prob
        else:
            direction = "NEUTRAL"
            emoji = "🟡"
            probability_val = 50.0

        # Basit güven aralığı (±%5 yaklaşımı)
        margin = 5.0
        ci_lower = round(max(0, probability_val - margin), 1)
        ci_upper = round(min(100, probability_val + margin), 1)

        # Güvenilirlik: sample_size > 30 ve olasılık > 55 ise güvenilir
        reliable = probability.get("sample_size", 0) >= 30 and probability_val >= 55

        horizons[h] = {
            "direction": direction,
            "emoji": emoji,
            "probability": round(probability_val, 1),
            "ci_lower": ci_lower,
            "ci_upper": ci_upper,
            "avg_return": avg_ret,
            "reliable": reliable,
        }

    sample_size = probability.get("sample_size", 0)
    best_h = min(horizons.keys()) if horizons else 3
    best = horizons.get(best_h, {})

    summary = (
        f"Benzer {sample_size} tarihsel koşul analiz edildi. "
        f"{best_h}G tahmini: {best.get('emoji','')} {best.get('direction','')} "
        f"(%{best.get('probability', 0):.0f} olasılık). "
        f"Trend rejimi: {trend_regime}."
    )

    return {
        "sample_size": sample_size,
        "model_type": "Tarihsel Olasılık (Backtest)",
        "summary": summary,
        "horizons": horizons,
    }

def run_engine():
    from core.data_sources import get_market_bundle
    from core.validators import validate_market_bundle

    bundle = get_market_bundle()

    # ── Veri doğrulama (Faz 1) ──
    validation = validate_market_bundle(bundle)

    if not validation["valid"]:
        error_msg = "Kritik veri doğrulama hatası:\n" + "\n".join(validation["errors"])
        return {"error": error_msg}

    eur_1d = bundle.get("eur_1d")
    if eur_1d is None or eur_1d.empty:
        return {"error": "EUR/USD verisi alınamadı. Lütfen biraz sonra tekrar deneyin."}

    scores, comments = build_scores(bundle)

    # ── Rejim tespiti ve Adaptive EDE (Faz 2) ──
    from regime.regime import detect_regime
    from regime.adaptive_weights import calculate_adaptive_ede

    regime_result = detect_regime(
        eur_df=eur_1d,
        vix=bundle.get("vix"),
        dxy_pct=bundle.get("dxy_pct"),
    )

    adaptive = calculate_adaptive_ede(scores, regime_result["regime"])

    # Adaptive EDE ana skor olarak kullanılır
    ede = adaptive["adaptive_ede"]
    static_ede = adaptive["static_ede"]

    decision = classify_decision(ede)

    data_quality = bundle.get("data_quality", {})
    data_quality_score = data_quality.get("score", 0)
    confidence_label = classify_confidence(data_quality_score)

    # Eski trend_regime uyumluluk için korunuyor
    trend_regime = regime_result["trend_direction"]
    market_regime = regime_result["regime"]

    sale_plan = build_sale_plan(ede, trend_regime, scores.get("MacroRisk", 50))

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
        "static_ede": static_ede,
        "ede_delta": adaptive["delta"],
        "market_regime": market_regime,
        "regime_confidence": regime_result["confidence"],
        "regime_description": regime_result["description"],
        "adaptive_explanation": adaptive["explanation"],
        "adaptive_weights": adaptive["weights_used"],
        "adaptive_contribution": adaptive["contribution"],
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
        "probability": probability,
        "formula_box_text": formula_box_text,
        "validation_warnings": validation["warnings"],
        "validation_errors": validation["errors"],
    }

    result["forecast"] = build_forecast(probability, ede, trend_regime)
    result["risk_note"] = build_risk_note(result)
    result["operation_summary"] = build_operation_summary(result)
    result["debug"] = {
        "sources": {
            "us2y_source": result["us2y_source"],
            "us10y_source": result["us10y_source"],
            "de2y_source": result["de2y_source"],
            "de10y_source": result["de10y_source"],
            "macro_source": result["macro_source"],
        },
        "scores": scores,
        "comments": comments,
        "data_quality": data_quality,
        "trend_regime": trend_regime,
        "market_regime": market_regime,
        "regime_detail": {
            "regime": regime_result["regime"],
            "confidence": regime_result["confidence"],
            "signals": {
                "risk_on": regime_result["signals"].risk_on_score,
                "risk_off": regime_result["signals"].risk_off_score,
                "trend": regime_result["signals"].trend_score,
                "range": regime_result["signals"].range_score,
            },
            "inputs": regime_result["inputs"],
        },
        "adaptive_ede": {
            "adaptive": adaptive["adaptive_ede"],
            "static": adaptive["static_ede"],
            "delta": adaptive["delta"],
        },
        "probability": probability,
        "validation": {
            "warnings": validation["warnings"],
            "errors": validation["errors"],
        },
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