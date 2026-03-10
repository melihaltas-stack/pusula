"""
engine/execution.py — Execution Optimizer

Pusulayı timing engine'den treasury decision engine'e dönüştürür.
Artık sadece "ne zaman" değil, "ne kadarını ne zaman" sorusuna
matematiksel olarak cevap verir.

Formül:
    sell_ratio = 0.50 * ede_factor + 0.30 * trend_factor + 0.20 * vol_factor

Regime-aware execution:
    RISK_OFF → Agresif satış, sabah ağırlıklı
    TREND    → Momentum satış, trendi takip
    RANGE    → Sabırlı satış, dirençte sat
    RISK_ON  → Minimal satış, EUR güçlü
"""

import logging
from typing import Optional

from core.indicators import clamp

logger = logging.getLogger("selvese.execution")


# ─────────────────────────────────────────────
# Regime execution parametreleri
# ─────────────────────────────────────────────
REGIME_PARAMS = {
    "RISK_OFF": {
        "morning_ratio": 0.65,     # sabah ağırlığı
        "min_sell": 20,            # minimum satış
        "regime_multiplier": 1.20, # rejim çarpanı
        "strategy": "Agresif satış. Sabah ağırlıklı, hızlı execution.",
    },
    "TREND": {
        "morning_ratio": 0.55,
        "min_sell": 15,
        "regime_multiplier": 1.05,
        "strategy": "Momentum satış. Trendi takip et.",
    },
    "RANGE": {
        "morning_ratio": 0.50,
        "min_sell": 10,
        "regime_multiplier": 0.85,
        "strategy": "Sabırlı satış. Dirençte sat, destekte bekle.",
    },
    "RISK_ON": {
        "morning_ratio": 0.50,
        "min_sell": 5,
        "regime_multiplier": 0.65,
        "strategy": "Minimal satış. EUR güçlü, bekle.",
    },
}

DEFAULT_PARAMS = {
    "morning_ratio": 0.60,
    "min_sell": 10,
    "regime_multiplier": 1.00,
    "strategy": "Standart execution.",
}


# ─────────────────────────────────────────────
# Faktör hesaplamaları
# ─────────────────────────────────────────────
def _ede_factor(ede: float) -> float:
    """EDE'den satış faktörü türet (0.0 – 1.0).

    Yüksek EDE → EUR satışı için uygun → yüksek faktör.
    """
    return clamp((ede - 20) / 80, 0.0, 1.0)


def _trend_factor(trend_direction: str, momentum_score: float = 50) -> float:
    """Trend yönü ve momentum'dan satış faktörü.

    DOWN trend + negatif momentum → yüksek faktör (agresif sat).
    UP trend + pozitif momentum → düşük faktör (bekle).
    """
    base = 0.5

    if trend_direction == "DOWN":
        base = 0.75
    elif trend_direction == "UP":
        base = 0.25

    # Momentum etkisi: yüksek momentum skoru → satış fırsatı
    mom_adj = (momentum_score - 50) / 200  # ±0.25 katkı
    return clamp(base + mom_adj, 0.0, 1.0)


def _volatility_factor(atr_pct: Optional[float], vix: Optional[float]) -> float:
    """Volatilite'den satış faktörü.

    Yüksek vol → daha büyük risk → pozisyon kapat → yüksek faktör.
    Düşük vol → sakin piyasa → sabırlı ol → orta faktör.
    """
    score = 0.5

    if atr_pct is not None:
        if atr_pct > 0.90:
            score += 0.20   # yüksek vol → sat
        elif atr_pct < 0.45:
            score -= 0.10   # düşük vol → bekle

    if vix is not None:
        if vix > 25:
            score += 0.15
        elif vix < 18:
            score -= 0.10

    return clamp(score, 0.0, 1.0)


# ─────────────────────────────────────────────
# Confidence hesaplama
# ─────────────────────────────────────────────
def _execution_confidence(
    data_quality_score: float,
    regime_confidence: float,
    ede: float,
) -> dict:
    """Execution önerisinin güven skoru.

    Yüksek (%70+): Model, veri ve rejim net.
    Orta (%50-70): Bazı belirsizlikler.
    Düşük (<50): Veri eksik, rejim geçiş dönemi.
    """
    # Veri kalitesi ağırlığı: %40
    dq_contrib = (data_quality_score / 100) * 40

    # Rejim netliği ağırlığı: %35
    regime_contrib = (regime_confidence / 100) * 35

    # EDE netliği: Çok yüksek veya çok düşük → daha net karar
    ede_clarity = abs(ede - 50) / 50  # 0=belirsiz, 1=net
    ede_contrib = ede_clarity * 25

    confidence = clamp(dq_contrib + regime_contrib + ede_contrib, 0, 100)

    if confidence >= 70:
        label = "Yüksek"
    elif confidence >= 50:
        label = "Orta"
    else:
        label = "Düşük"

    return {
        "score": round(confidence, 1),
        "label": label,
        "breakdown": {
            "data_quality": round(dq_contrib, 1),
            "regime_clarity": round(regime_contrib, 1),
            "ede_clarity": round(ede_contrib, 1),
        },
    }


# ─────────────────────────────────────────────
# Waterfall açıklanabilirlik
# ─────────────────────────────────────────────
def _build_waterfall(steps: list) -> list:
    """Waterfall adımlarını oluşturur.

    Her adım: {"label": str, "delta": int, "running_total": int, "reason": str}
    """
    waterfall = []
    running = 0

    for step in steps:
        running += step["delta"]
        running = max(0, min(100, running))
        waterfall.append({
            "label": step["label"],
            "delta": step["delta"],
            "running_total": running,
            "reason": step["reason"],
        })

    return waterfall


# ─────────────────────────────────────────────
# Ana execution optimizer
# ─────────────────────────────────────────────
def optimize_execution(
    ede: float,
    trend_direction: str,
    market_regime: str,
    momentum_score: float = 50,
    atr_pct: Optional[float] = None,
    vix: Optional[float] = None,
    macro_score: float = 50,
    data_quality_score: float = 70,
    regime_confidence: float = 50,
) -> dict:
    """Optimal satış planını matematiksel olarak hesaplar.

    Args:
        ede: Adaptive EDE skoru (0-100)
        trend_direction: UP | DOWN | SIDEWAYS
        market_regime: RISK_ON | RISK_OFF | TREND | RANGE
        momentum_score: Momentum alt skoru (0-100)
        atr_pct: ATR yüzdesi
        vix: VIX seviyesi
        macro_score: Makro risk alt skoru (0-100)
        data_quality_score: Veri kalite skoru (0-100)
        regime_confidence: Rejim tespit güveni (0-100)

    Returns:
        {
            "sell_ratio": float,         # 0.0 – 1.0
            "daily_units": int,          # 0 – 100
            "morning_units": int,
            "afternoon_units": int,
            "plan_label": str,
            "confidence": dict,
            "waterfall": list,
            "factors": dict,
            "regime_strategy": str,
            "explanation": str,
        }
    """
    # ── Faktörleri hesapla ──
    ef = _ede_factor(ede)
    tf = _trend_factor(trend_direction, momentum_score)
    vf = _volatility_factor(atr_pct, vix)

    # ── Sell ratio formülü ──
    raw_ratio = 0.50 * ef + 0.30 * tf + 0.20 * vf
    raw_ratio = clamp(raw_ratio, 0.0, 1.0)

    # ── Raw units (0-100) ──
    raw_units = int(round(raw_ratio * 100))

    # ── Waterfall adımları ──
    waterfall_steps = [
        {
            "label": "Base (EDE faktör)",
            "delta": int(round(ef * 50)),
            "reason": f"EDE {ede:.0f} → faktör {ef:.2f}",
        },
        {
            "label": "Trend faktör",
            "delta": int(round(tf * 30)),
            "reason": f"Trend {trend_direction}, Momentum {momentum_score:.0f} → faktör {tf:.2f}",
        },
        {
            "label": "Volatilite faktör",
            "delta": int(round(vf * 20)),
            "reason": f"ATR {'%.2f' % atr_pct if atr_pct else 'N/A'}%, VIX {'%.1f' % vix if vix else 'N/A'} → faktör {vf:.2f}",
        },
    ]

    # ── Makro risk freni ──
    macro_brake = 0
    macro_reason = "Makro risk fren gerektirmiyor"
    if macro_score < 35:
        macro_brake = -20
        macro_reason = "Makro risk yüksek → satış 20 birim azaltıldı"
    elif macro_score < 45:
        macro_brake = -10
        macro_reason = "Makro risk orta-yüksek → satış 10 birim azaltıldı"

    if macro_brake != 0:
        waterfall_steps.append({
            "label": "Makro risk freni",
            "delta": macro_brake,
            "reason": macro_reason,
        })

    # ── Rejim ayarı ──
    params = REGIME_PARAMS.get(market_regime, DEFAULT_PARAMS)
    regime_mult = params["regime_multiplier"]

    pre_regime = raw_units + macro_brake
    post_regime = int(round(pre_regime * regime_mult))
    regime_delta = post_regime - pre_regime

    if regime_delta != 0:
        direction = "artırıldı" if regime_delta > 0 else "azaltıldı"
        waterfall_steps.append({
            "label": f"Rejim ayarı ({market_regime})",
            "delta": regime_delta,
            "reason": f"{market_regime} rejimi → çarpan {regime_mult:.2f}, {abs(regime_delta)} birim {direction}",
        })

    # ── Final units ──
    waterfall = _build_waterfall(waterfall_steps)
    final_units = waterfall[-1]["running_total"] if waterfall else raw_units
    final_units = max(params["min_sell"], min(100, final_units))

    # ── Sabah / Öğleden sonra bölünmesi ──
    morning_ratio = params["morning_ratio"]
    morning_units = int(round(final_units * morning_ratio))
    afternoon_units = max(0, final_units - morning_units)

    # ── Plan etiketi ──
    if final_units >= 70:
        plan_label = "Agresif satış"
    elif final_units >= 40:
        plan_label = "Standart-üstü satış"
    elif final_units >= 25:
        plan_label = "Standart operasyon"
    else:
        plan_label = "Zorunlu minimum satış"

    # ── Confidence ──
    confidence = _execution_confidence(data_quality_score, regime_confidence, ede)

    # ── Sell ratio ──
    sell_ratio = round(final_units / 100, 2)

    # ── Açıklama ──
    explanation = (
        f"{params['strategy']} "
        f"EDE {ede:.0f}, {trend_direction} trend, {market_regime} rejimi. "
        f"Toplam {final_units}/100 birim satış önerilir; "
        f"{morning_units} birim sabah, {afternoon_units} birim öğleden sonra. "
        f"Güven: {confidence['label']} ({confidence['score']:.0f}%)."
    )

    return {
        "sell_ratio": sell_ratio,
        "daily_units": final_units,
        "morning_units": morning_units,
        "afternoon_units": afternoon_units,
        "plan_label": plan_label,
        "confidence": confidence,
        "waterfall": waterfall,
        "factors": {
            "ede_factor": round(ef, 3),
            "trend_factor": round(tf, 3),
            "volatility_factor": round(vf, 3),
            "raw_ratio": round(raw_ratio, 3),
            "raw_units": raw_units,
            "macro_brake": macro_brake,
            "regime_multiplier": regime_mult,
        },
        "regime_strategy": params["strategy"],
        "explanation": explanation,
    }


# ─────────────────────────────────────────────
# Gün içi revize
# ─────────────────────────────────────────────
def revise_afternoon(
    morning_executed: int,
    original_plan: dict,
    current_ede: float,
    current_trend: str,
    current_regime: str,
    **kwargs,
) -> dict:
    """Sabah planı uygulandıktan sonra öğleden sonra için revize öneri.

    Piyasa koşulları sabahtan beri değiştiyse plan güncellenir.

    Args:
        morning_executed: Sabah gerçekleştirilen satış birimi
        original_plan: Sabahki optimize_execution çıktısı
        current_ede: Güncel EDE skoru
        current_trend: Güncel trend yönü
        current_regime: Güncel market rejimi
        **kwargs: optimize_execution'a geçirilecek ek parametreler

    Returns:
        {
            "revised_afternoon": int,
            "original_afternoon": int,
            "change": int,
            "reason": str,
            "new_total": int,
        }
    """
    original_afternoon = original_plan.get("afternoon_units", 0)
    original_daily = original_plan.get("daily_units", 0)

    # Güncel koşullarla yeni plan hesapla
    new_plan = optimize_execution(
        ede=current_ede,
        trend_direction=current_trend,
        market_regime=current_regime,
        **kwargs,
    )

    new_daily = new_plan["daily_units"]

    # Kalan birim: yeni plan - sabah satılan
    revised_afternoon = max(0, min(100 - morning_executed, new_daily - morning_executed))

    change = revised_afternoon - original_afternoon

    if abs(change) <= 2:
        reason = f"Koşullar değişmedi. Orijinal plan korunuyor."
    elif change > 0:
        reason = (
            f"Piyasa koşulları satış lehine değişti "
            f"(EDE: {current_ede:.0f}, rejim: {current_regime}). "
            f"Öğleden sonra {change} birim artırıldı."
        )
    else:
        reason = (
            f"Piyasa koşulları yumuşadı "
            f"(EDE: {current_ede:.0f}, rejim: {current_regime}). "
            f"Öğleden sonra {abs(change)} birim azaltıldı."
        )

    return {
        "revised_afternoon": revised_afternoon,
        "original_afternoon": original_afternoon,
        "change": change,
        "reason": reason,
        "new_total": morning_executed + revised_afternoon,
        "morning_executed": morning_executed,
    }
