def base_units_from_ede(ede, horizon="medium_term"):
    thresholds = {
        "short_term": (58, 48, 38),
        "medium_term": (65, 52, 40),
        "long_term": (68, 55, 43),
    }
    strong, ready, prep = thresholds.get(horizon, thresholds["medium_term"])

    if ede >= strong:
        return 85, "Güçlü satış penceresi"
    if ede >= ready:
        return 50, "Kademeli satış uygun"
    if ede >= prep:
        return 30, "Hazırlan / teyit bekle"
    return 15, "Zayıf satış günü"


def apply_macro_brake(units, macro_score):
    if macro_score is None:
        return units, "Makro veri etkisi uygulanmadı"

    if macro_score < 35:
        return max(10, units - 25), "Makro risk yüksek → satış bir kademe düşürüldü"
    if macro_score < 45:
        return max(10, units - 15), "Makro risk orta-yüksek → satış azaltıldı"
    return units, "Makro risk fren gerektirmiyor"


def apply_trend_adjustment(units, trend_regime):
    if trend_regime == "UP":
        adjusted = max(10, int(round(units * 0.8)))
        return adjusted, "Yukarı trend → satış oranı %20 azaltıldı"
    if trend_regime == "DOWN":
        adjusted = min(100, int(round(units * 1.2)))
        return adjusted, "Aşağı trend → satış oranı %20 artırıldı"
    return units, "Yatay trend → ek ayar yapılmadı"


def split_execution(units):
    morning = int(round(units * 0.6))
    afternoon = max(0, units - morning)
    return morning, afternoon


def apply_realism_brake(units, probability_summary=None, data_quality_score=None):
    notes = []
    adjusted = units

    if data_quality_score is not None and data_quality_score < 65:
        adjusted = max(10, adjusted - 10)
        notes.append("Veri güveni orta-altı olduğu için satış 10 birim azaltıldı")

    if not probability_summary or probability_summary.get("sample_size", 0) <= 0:
        return adjusted, " | ".join(notes) if notes else "Olasılık freni uygulanmadı"

    h3 = probability_summary.get("horizons", {}).get(3)
    if not h3:
        return adjusted, " | ".join(notes) if notes else "Olasılık freni uygulanmadı"

    prob = h3.get("down_probability", 50)
    ci_width = h3.get("ci_width", 100)
    reliable = h3.get("reliable", False)
    sample_size = probability_summary.get("sample_size", 0)

    if not reliable or sample_size < 20 or ci_width >= 25:
        adjusted = max(10, adjusted - 10)
        notes.append("Kısa vade olasılık örneklemi zayıf olduğu için satış 10 birim azaltıldı")
    elif prob < 52:
        adjusted = max(10, adjusted - 15)
        notes.append("3 günlük düşüş olasılığı zayıf olduğu için satış 15 birim azaltıldı")
    elif prob >= 60 and ci_width <= 18:
        adjusted = min(100, adjusted + 5)
        notes.append("3 günlük düşüş olasılığı güçlü olduğu için satış 5 birim artırıldı")

    return adjusted, " | ".join(notes) if notes else "Olasılık freni uygulanmadı"


def build_sale_plan(ede, trend_regime, macro_score, horizon="medium_term", probability_summary=None, data_quality_score=None):
    base_units, base_reason = base_units_from_ede(ede, horizon=horizon)
    after_macro, macro_reason = apply_macro_brake(base_units, macro_score)
    after_trend, trend_reason = apply_trend_adjustment(after_macro, trend_regime)
    final_units, realism_reason = apply_realism_brake(
        after_trend,
        probability_summary=probability_summary,
        data_quality_score=data_quality_score,
    )
    morning_units, afternoon_units = split_execution(final_units)

    if final_units >= 70:
        plan_label = "Agresif satış"
    elif final_units >= 40:
        plan_label = "Standart-üstü satış"
    elif final_units >= 25:
        plan_label = "Standart operasyon"
    else:
        plan_label = "Zorunlu minimum satış"

    explanation = (
        f"{base_reason}. {macro_reason}. {trend_reason}. {realism_reason}. "
        f"Bugün toplam {final_units}/100 birim satış önerilir; "
        f"{morning_units} birim sabah, {afternoon_units} birim öğleden sonra."
    )

    return {
        "daily_units": final_units,
        "morning_units": morning_units,
        "afternoon_units": afternoon_units,
        "plan_label": plan_label,
        "explanation": explanation,
    }
