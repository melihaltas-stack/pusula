"""
Bu script engine.py'ye forecast fonksiyonu ekler.
Terminalde çalıştır: python3 patch_engine.py
"""

import re

ENGINE_PATH = "/Users/melihaltas/Desktop/Pusula/engine/engine.py"

FORECAST_FUNC = '''

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
'''

INSERT_BEFORE = 'def run_engine():'

with open(ENGINE_PATH, "r", encoding="utf-8") as f:
    content = f.read()

if "def build_forecast(" in content:
    print("build_forecast zaten mevcut, güncelleniyor...")
    # Eski fonksiyonu kaldır
    content = re.sub(
        r'\ndef build_forecast\(.*?\n(?=\ndef |\nclass )',
        '\n',
        content,
        flags=re.DOTALL
    )

# Fonksiyonu ekle
content = content.replace(INSERT_BEFORE, FORECAST_FUNC + "\n" + INSERT_BEFORE)

# run_engine içine forecast ekle
# "probability" atandıktan sonra forecast'i ekle
OLD = '    result["risk_note"] = build_risk_note(result)'
NEW = '''    result["forecast"] = build_forecast(probability, ede, trend_regime)
    result["risk_note"] = build_risk_note(result)'''

if 'result["forecast"]' not in content:
    content = content.replace(OLD, NEW)

with open(ENGINE_PATH, "w", encoding="utf-8") as f:
    f.write(content)

print("✅ engine.py güncellendi! Uygulamayı yeniden başlatın.")
