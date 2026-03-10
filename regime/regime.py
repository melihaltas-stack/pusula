"""
regime/regime.py — Piyasa Rejimi Tespit Motoru

4 ana rejim tanımlar:
    RISK_ON   → VIX düşük, DXY zayıf, riskli varlıklar güçlü
    RISK_OFF  → VIX yüksek, USD güçlü, güvenli liman talebi
    TREND     → Güçlü yönlü hareket (UP veya DOWN)
    RANGE     → Piyasa yatay, düşük volatilite

Girdiler:
    - VIX seviyesi ve kısa vadeli trendi
    - DXY momentum (3 günlük değişim)
    - EUR/USD trend yapısı (MA dizilimi)
    - ATR yüzdesi (volatilite seviyesi)

Whipsaw koruması:
    Rejim değişikliği için minimum 2 gün aynı rejimde kalma kuralı.
"""

import logging
from dataclasses import dataclass
from typing import Optional

from core.indicators import safe_float, sma, atr, momentum_pct

logger = logging.getLogger("selvese.regime")


# ─────────────────────────────────────────────
# Rejim sabitleri
# ─────────────────────────────────────────────
RISK_ON = "RISK_ON"
RISK_OFF = "RISK_OFF"
TREND = "TREND"
RANGE = "RANGE"

ALL_REGIMES = (RISK_ON, RISK_OFF, TREND, RANGE)


# ─────────────────────────────────────────────
# Eşik değerleri (config.yaml'a taşınabilir)
# ─────────────────────────────────────────────
VIX_LOW = 18.0          # altında risk-on sinyali
VIX_HIGH = 25.0         # üstünde risk-off sinyali
DXY_WEAK_PCT = -0.3     # 3G DXY değişimi bu altında → zayıflama
DXY_STRONG_PCT = 0.3    # 3G DXY değişimi bu üstünde → güçlenme
ATR_LOW_PCT = 0.45      # düşük volatilite eşiği
ATR_HIGH_PCT = 0.90     # yüksek volatilite eşiği
MIN_REGIME_DAYS = 2     # whipsaw koruması


# ─────────────────────────────────────────────
# Rejim sinyal puanlama
# ─────────────────────────────────────────────
@dataclass
class RegimeSignals:
    """Her rejim için ham sinyal puanları (0-100)."""
    risk_on_score: float = 0.0
    risk_off_score: float = 0.0
    trend_score: float = 0.0
    range_score: float = 0.0


def _compute_signals(
    vix: Optional[float],
    dxy_pct: Optional[float],
    ma20: Optional[float],
    ma50: Optional[float],
    ma100: Optional[float],
    atr_pct: Optional[float],
) -> RegimeSignals:
    """Ham piyasa verilerinden rejim sinyalleri üretir.

    Her rejim için 0-100 arası bir skor hesaplar.
    En yüksek skor kazanır.
    """
    signals = RegimeSignals()

    # ── VIX sinyali ──
    if vix is not None:
        if vix < VIX_LOW:
            signals.risk_on_score += 35
            signals.trend_score += 10
        elif vix > VIX_HIGH:
            signals.risk_off_score += 40
        else:
            # Orta VIX → trend veya range
            signals.trend_score += 10
            signals.range_score += 15

    # ── DXY momentum sinyali ──
    if dxy_pct is not None:
        if dxy_pct < DXY_WEAK_PCT:
            # DXY zayıflıyor → risk-on
            signals.risk_on_score += 25
        elif dxy_pct > DXY_STRONG_PCT:
            # DXY güçleniyor → risk-off
            signals.risk_off_score += 25
        else:
            # DXY nötr
            signals.range_score += 10

    # ── MA dizilimi (trend yapısı) ──
    if None not in (ma20, ma50, ma100):
        if ma20 > ma50 > ma100:
            # Güçlü yukarı trend
            signals.trend_score += 40
            signals.risk_on_score += 15
        elif ma20 < ma50 < ma100:
            # Güçlü aşağı trend
            signals.trend_score += 40
            signals.risk_off_score += 10
        else:
            # MA'lar iç içe → range veya geçiş
            signals.range_score += 35
            signals.trend_score -= 10

    # ── ATR (volatilite) sinyali ──
    if atr_pct is not None:
        if atr_pct < ATR_LOW_PCT:
            # Düşük vol → range
            signals.range_score += 25
            signals.trend_score -= 5
        elif atr_pct > ATR_HIGH_PCT:
            # Yüksek vol → risk-off veya güçlü trend
            signals.risk_off_score += 15
            signals.trend_score += 15
        else:
            # Normal vol
            signals.trend_score += 10

    # Minimum 0
    signals.risk_on_score = max(0, signals.risk_on_score)
    signals.risk_off_score = max(0, signals.risk_off_score)
    signals.trend_score = max(0, signals.trend_score)
    signals.range_score = max(0, signals.range_score)

    return signals


# ─────────────────────────────────────────────
# Ana rejim tespit fonksiyonu
# ─────────────────────────────────────────────
def detect_regime(
    eur_df,
    vix: Optional[float] = None,
    dxy_pct: Optional[float] = None,
    previous_regime: Optional[str] = None,
    previous_regime_days: int = 0,
) -> dict:
    """Mevcut piyasa rejimini tespit eder.

    Args:
        eur_df: EUR/USD OHLC DataFrame (en az 120 satır)
        vix: Güncel VIX seviyesi
        dxy_pct: DXY 3 günlük yüzde değişimi
        previous_regime: Bir önceki rejim (whipsaw koruması için)
        previous_regime_days: Mevcut rejimde kaç gün kalındı

    Returns:
        {
            "regime": str,           # RISK_ON | RISK_OFF | TREND | RANGE
            "confidence": float,     # 0-100 arası güven
            "signals": RegimeSignals,
            "trend_direction": str,  # UP | DOWN | SIDEWAYS
            "description": str,      # Türkçe açıklama
            "inputs": dict,          # Kullanılan girdiler
        }
    """
    # ── EUR/USD teknik verileri çıkar ──
    ma20, ma50, ma100, atr_pct_val = None, None, None, None
    trend_direction = "SIDEWAYS"

    if eur_df is not None and not eur_df.empty and len(eur_df) >= 120:
        close = eur_df["Close"]

        ma20 = safe_float(sma(close, 20).iloc[-1])
        ma50 = safe_float(sma(close, 50).iloc[-1])
        ma100 = safe_float(sma(close, 100).iloc[-1])

        atr_val = safe_float(atr(eur_df, 14).iloc[-1])
        last_close = safe_float(close.iloc[-1])
        if atr_val is not None and last_close not in (None, 0):
            atr_pct_val = (atr_val / last_close) * 100

        # Trend yönü
        if None not in (ma20, ma50, ma100):
            if ma20 > ma50 > ma100:
                trend_direction = "UP"
            elif ma20 < ma50 < ma100:
                trend_direction = "DOWN"

    # ── Sinyalleri hesapla ──
    signals = _compute_signals(vix, dxy_pct, ma20, ma50, ma100, atr_pct_val)

    # ── En yüksek skoru bul ──
    score_map = {
        RISK_ON: signals.risk_on_score,
        RISK_OFF: signals.risk_off_score,
        TREND: signals.trend_score,
        RANGE: signals.range_score,
    }

    raw_regime = max(score_map, key=score_map.get)
    max_score = score_map[raw_regime]
    total_score = sum(score_map.values()) or 1
    confidence = round((max_score / total_score) * 100, 1)

    # ── Whipsaw koruması ──
    regime = raw_regime
    if previous_regime is not None and previous_regime != raw_regime:
        if previous_regime_days < MIN_REGIME_DAYS:
            regime = previous_regime
            logger.info(
                "Whipsaw koruması: %s → %s engellendi (gün: %d < %d)",
                previous_regime, raw_regime, previous_regime_days, MIN_REGIME_DAYS,
            )

    # ── Açıklama oluştur ──
    descriptions = {
        RISK_ON: "Risk-on ortamı: VIX düşük, DXY zayıf. Teknik ve momentum göstergeleri baskın.",
        RISK_OFF: "Risk-off ortamı: VIX yüksek, USD güçlü. Faiz farkı ve DXY göstergeleri baskın.",
        TREND: f"Trend piyasası ({trend_direction}): Güçlü yönlü hareket. Trend göstergeleri baskın.",
        RANGE: "Yatay piyasa: Düşük volatilite, MA'lar iç içe. Formasyon ve mean reversion baskın.",
    }

    inputs = {
        "vix": vix,
        "dxy_pct": dxy_pct,
        "ma20": round(ma20, 5) if ma20 else None,
        "ma50": round(ma50, 5) if ma50 else None,
        "ma100": round(ma100, 5) if ma100 else None,
        "atr_pct": round(atr_pct_val, 3) if atr_pct_val else None,
    }

    return {
        "regime": regime,
        "confidence": confidence,
        "signals": signals,
        "trend_direction": trend_direction,
        "description": descriptions.get(regime, "Bilinmiyor"),
        "inputs": inputs,
        "raw_regime": raw_regime,
        "scores": score_map,
    }
