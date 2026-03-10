"""
backtest/confidence.py — Güven Aralığı Hesaplama

Olasılık tahminlerine %95 güven aralığı ekler.
Wilson score interval kullanır (küçük örneklemlerde
normal approximation'dan daha doğru).
"""

import math
import logging
from typing import Optional

logger = logging.getLogger("selvese.confidence")

# Minimum güvenilir örneklem büyüklüğü
MIN_SAMPLE_SIZE = 30

# Z-score for 95% confidence
Z_95 = 1.96


def wilson_interval(successes: int, total: int, z: float = Z_95) -> dict:
    """Wilson score interval hesaplar.

    Normal approximation küçük örneklemlerde hatalı sonuç verir.
    Wilson interval n < 30'da bile güvenilirdir.

    Args:
        successes: Başarılı olay sayısı (ör: düşüş gerçekleşen gün)
        total: Toplam gözlem sayısı

    Returns:
        {
            "point": float,     # nokta tahmin (%)
            "lower": float,     # alt sınır (%)
            "upper": float,     # üst sınır (%)
            "ci_width": float,  # aralık genişliği
            "reliable": bool,   # örneklem yeterli mi
        }
    """
    if total <= 0:
        return {
            "point": 0.0,
            "lower": 0.0,
            "upper": 0.0,
            "ci_width": 0.0,
            "reliable": False,
        }

    p_hat = successes / total
    z2 = z * z

    denominator = 1 + z2 / total
    center = (p_hat + z2 / (2 * total)) / denominator
    spread = (z / denominator) * math.sqrt(
        (p_hat * (1 - p_hat) / total) + (z2 / (4 * total * total))
    )

    lower = max(0, center - spread)
    upper = min(1, center + spread)

    return {
        "point": round(p_hat * 100, 1),
        "lower": round(lower * 100, 1),
        "upper": round(upper * 100, 1),
        "ci_width": round((upper - lower) * 100, 1),
        "reliable": total >= MIN_SAMPLE_SIZE,
    }


def add_confidence_to_horizons(horizons: dict, sample_size: int) -> dict:
    """Mevcut horizon olasılıklarına güven aralığı ekler.

    Args:
        horizons: {3: {"down_probability": 61.0, "avg_return": -0.12}, ...}
        sample_size: Toplam benzer koşul sayısı

    Returns:
        Genişletilmiş horizons dict:
        {3: {
            "down_probability": 61.0,
            "avg_return": -0.12,
            "ci_lower": 55.0,
            "ci_upper": 67.0,
            "ci_width": 12.0,
            "reliable": True,
        }, ...}
    """
    enhanced = {}

    for horizon, data in horizons.items():
        prob = data.get("down_probability", 50.0)

        # Wilson interval için başarı sayısı hesapla
        successes = int(round(prob / 100 * sample_size))
        ci = wilson_interval(successes, sample_size)

        enhanced[horizon] = {
            **data,
            "ci_lower": ci["lower"],
            "ci_upper": ci["upper"],
            "ci_width": ci["width"] if "width" in ci else ci["ci_width"],
            "reliable": ci["reliable"],
        }

    return enhanced


def format_probability_with_ci(prob: float, ci_lower: float, ci_upper: float, reliable: bool) -> str:
    """Olasılığı güven aralığı ile formatlar.

    Örnekler:
        "%61 (CI: %55–%67)"
        "%61 (CI: %55–%67) ⚠ Düşük örneklem"
    """
    base = f"%{prob:.0f} (CI: %{ci_lower:.0f}\u2013%{ci_upper:.0f})"
    if not reliable:
        return base + " \u26A0 D\u00FC\u015F\u00FCk \u00F6rneklem"
    return base
