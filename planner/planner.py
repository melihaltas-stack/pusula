def base_units_from_ede(ede):
    if ede >= 65:
        return 85, "Güçlü satış penceresi"
    if ede >= 52:
        return 50, "Kademeli satış uygun"
    if ede >= 40:
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


def build_sale_plan(ede, trend_regime, macro_score):
    base_units, base_reason = base_units_from_ede(ede)
    after_macro, macro_reason = apply_macro_brake(base_units, macro_score)
    final_units, trend_reason = apply_trend_adjustment(after_macro, trend_regime)
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
        f"{base_reason}. {macro_reason}. {trend_reason}. "
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