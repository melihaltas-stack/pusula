"""
regime/adaptive_weights.py — Adaptif Ağırlık Motoru

Rejim tespit edildikten sonra EDE ağırlıklarını otomatik olarak değiştirir.

                RISK_ON   RISK_OFF   TREND    RANGE    Statik(mevcut)
    DXY          %15       %35       %15      %15      %22
    Faiz         %10       %30       %10      %10      %18
    Risk         %10       %20       %5       %10      %12
    Teknik       %30       %10       %35      %15      %22
    Form         %15       %5        %5       %30      %12
    Volatilite   %10       %0        %10      %20      %7
    Momentum     %10       %0        %20      %0       —

Momentum yeni bir alt skor olarak eklenir.
Tüm ağırlık setlerinin toplamı = 1.00 (doğrulanmış).
"""

import logging
from typing import Optional

from regime.regime import RISK_ON, RISK_OFF, TREND, RANGE, ALL_REGIMES

logger = logging.getLogger("selvese.adaptive_weights")


# ─────────────────────────────────────────────
# Statik ağırlıklar (mevcut model — fallback)
# ─────────────────────────────────────────────
STATIC_WEIGHTS = {
    "DXY":        0.22,
    "Faiz":       0.18,
    "Risk":       0.12,
    "Teknik":     0.22,
    "Form":       0.12,
    "Volatilite": 0.07,
    "MacroRisk":  0.07,
}


# ─────────────────────────────────────────────
# Rejime göre adaptif ağırlıklar
# ─────────────────────────────────────────────
ADAPTIVE_WEIGHTS = {
    RISK_ON: {
        "DXY":        0.12,
        "Faiz":       0.08,
        "Risk":       0.10,
        "Teknik":     0.25,
        "Form":       0.13,
        "Volatilite": 0.10,
        "MacroRisk":  0.05,
        "Momentum":   0.17,
    },
    RISK_OFF: {
        "DXY":        0.30,
        "Faiz":       0.25,
        "Risk":       0.20,
        "Teknik":     0.08,
        "Form":       0.04,
        "Volatilite": 0.03,
        "MacroRisk":  0.10,
        "Momentum":   0.00,
    },
    TREND: {
        "DXY":        0.10,
        "Faiz":       0.08,
        "Risk":       0.05,
        "Teknik":     0.30,
        "Form":       0.05,
        "Volatilite": 0.07,
        "MacroRisk":  0.05,
        "Momentum":   0.30,
    },
    RANGE: {
        "DXY":        0.12,
        "Faiz":       0.08,
        "Risk":       0.10,
        "Teknik":     0.10,
        "Form":       0.28,
        "Volatilite": 0.20,
        "MacroRisk":  0.05,
        "Momentum":   0.07,
    },
}


def _validate_weight_set(weights: dict, label: str) -> bool:
    """Ağırlık setinin toplamının 1.00 olduğunu doğrular."""
    total = sum(weights.values())
    if abs(total - 1.0) > 0.001:
        logger.error("%s: ağırlık toplamı %.4f != 1.00", label, total)
        return False
    return True


# Modül yüklenirken tüm ağırlık setlerini doğrula
for _regime in ALL_REGIMES:
    assert _validate_weight_set(ADAPTIVE_WEIGHTS[_regime], f"ADAPTIVE[{_regime}]"), \
        f"{_regime} ağırlık toplamı 1.00 değil!"


# ─────────────────────────────────────────────
# Ana fonksiyonlar
# ─────────────────────────────────────────────
def get_adaptive_weights(regime: str) -> dict:
    """Verilen rejim için ağırlık setini döndürür.

    Args:
        regime: RISK_ON | RISK_OFF | TREND | RANGE

    Returns:
        Ağırlık dict'i (toplam = 1.00).
        Bilinmeyen rejim → STATIC_WEIGHTS fallback.
    """
    if regime in ADAPTIVE_WEIGHTS:
        return ADAPTIVE_WEIGHTS[regime].copy()

    logger.warning("Bilinmeyen rejim '%s', statik ağırlıklar kullanılıyor", regime)
    return STATIC_WEIGHTS.copy()


def get_static_weights() -> dict:
    """Statik (mevcut model) ağırlıkları döndürür."""
    return STATIC_WEIGHTS.copy()


def calculate_adaptive_ede(scores: dict, regime: str) -> dict:
    """Adaptive EDE hesaplar.

    Hem adaptif hem statik skoru birlikte döndürür
    (karşılaştırma için).

    Args:
        scores: Alt skor dict'i (DXY, Faiz, Risk, Teknik, Form, Volatilite, MacroRisk, Momentum)
        regime: Mevcut piyasa rejimi

    Returns:
        {
            "adaptive_ede": float,
            "static_ede": float,
            "delta": float,           # adaptive - static
            "regime": str,
            "weights_used": dict,     # kullanılan ağırlıklar
            "contribution": dict,     # her göstergenin EDE'ye katkısı
            "explanation": str,       # Türkçe açıklama
        }
    """
    # ── Statik EDE ──
    static_w = get_static_weights()
    static_ede = 0.0
    for key, weight in static_w.items():
        static_ede += scores.get(key, 50) * weight
    static_ede = round(static_ede, 1)

    # ── Adaptive EDE ──
    adaptive_w = get_adaptive_weights(regime)
    adaptive_ede = 0.0
    contribution = {}

    for key, weight in adaptive_w.items():
        score_val = scores.get(key, 50)
        contrib = score_val * weight
        adaptive_ede += contrib
        if weight > 0:
            contribution[key] = {
                "score": score_val,
                "weight": weight,
                "contribution": round(contrib, 2),
                "weight_pct": f"%{weight * 100:.0f}",
            }

    adaptive_ede = round(adaptive_ede, 1)
    delta = round(adaptive_ede - static_ede, 1)

    # ── Sıralı katkı (en yüksekten düşüğe) ──
    sorted_contrib = sorted(
        contribution.items(),
        key=lambda x: x[1]["contribution"],
        reverse=True,
    )

    # ── Açıklama ──
    top_3 = sorted_contrib[:3]
    top_names = ", ".join(f"{k} (%{v['weight']*100:.0f})" for k, v in top_3)

    regime_labels = {
        "RISK_ON": "Risk-on",
        "RISK_OFF": "Risk-off",
        "TREND": "Trend",
        "RANGE": "Range (yatay)",
    }
    regime_label = regime_labels.get(regime, regime)

    if delta > 0:
        delta_text = f"Adaptive model statikten {delta} puan yüksek"
    elif delta < 0:
        delta_text = f"Adaptive model statikten {abs(delta)} puan düşük"
    else:
        delta_text = "Adaptive ve statik model aynı"

    explanation = (
        f"{regime_label} rejiminde en etkili göstergeler: {top_names}. "
        f"Adaptive EDE: {adaptive_ede}, Statik EDE: {static_ede}. "
        f"{delta_text}."
    )

    return {
        "adaptive_ede": adaptive_ede,
        "static_ede": static_ede,
        "delta": delta,
        "regime": regime,
        "weights_used": adaptive_w,
        "contribution": dict(sorted_contrib),
        "explanation": explanation,
    }


def build_weight_comparison(regime: str) -> list:
    """Statik ve adaptif ağırlıkları karşılaştırma tablosu olarak döndürür.

    UI'da tablo veya bar chart için kullanılır.

    Returns:
        [{
            "category": str,
            "static_weight": float,
            "adaptive_weight": float,
            "change": str,  # "↑", "↓", "="
        }, ...]
    """
    static_w = get_static_weights()
    adaptive_w = get_adaptive_weights(regime)

    all_keys = list(dict.fromkeys(list(adaptive_w.keys()) + list(static_w.keys())))

    rows = []
    for key in all_keys:
        sw = static_w.get(key, 0)
        aw = adaptive_w.get(key, 0)

        if aw > sw + 0.01:
            change = "\u2191"   # ↑
        elif aw < sw - 0.01:
            change = "\u2193"   # ↓
        else:
            change = "="

        rows.append({
            "category": key,
            "static_weight": sw,
            "adaptive_weight": aw,
            "change": change,
        })

    return rows
