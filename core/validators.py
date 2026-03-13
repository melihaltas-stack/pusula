"""
core/validators.py — Veri Doğrulama Katmanı

Tüm dış kaynaklardan gelen veri, işleme alınmadan önce
bu modüldeki fonksiyonlar ile doğrulanır.

Doğrulanmamış veri ile üretilen her skor = potansiyel yanlış karar.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import pandas as pd

logger = logging.getLogger("selvese.validators")


# ─────────────────────────────────────────────
# Doğrulama sonucu
# ─────────────────────────────────────────────
@dataclass
class ValidationResult:
    """Tek bir doğrulama kontrolünün sonucu."""
    valid: bool
    value: object = None          # temizlenmiş değer (valid ise)
    warnings: list = field(default_factory=list)
    error: Optional[str] = None   # reject nedeni

    @property
    def ok(self) -> bool:
        return self.valid

    def __bool__(self) -> bool:
        return self.valid


# ─────────────────────────────────────────────
# Geçerli aralıklar (config'e taşınabilir)
# ─────────────────────────────────────────────
RANGES = {
    "EUR/USD":  {"min": 0.50, "max": 2.00, "warn_daily_pct": 3.0},
    "DXY":      {"min": 60.0, "max": 130.0, "warn_3d_pct": 3.0},
    "VIX":      {"min": 0.0,  "max": 90.0,  "warn_high": 40.0},
    "US2Y":     {"min": -2.0, "max": 15.0},
    "US10Y":    {"min": -2.0, "max": 15.0},
    "DE2Y":     {"min": -3.0, "max": 12.0},
    "DE10Y":    {"min": -3.0, "max": 12.0},
}

# Veri tazelik eşikleri (saniye)
FRESHNESS_FRESH   = 300    # 5 dakika
FRESHNESS_WARNING = 900    # 15 dakika


# ─────────────────────────────────────────────
# Temel doğrulayıcılar
# ─────────────────────────────────────────────
def validate_range(value, name: str) -> ValidationResult:
    """Değerin tanımlı geçerli aralıkta olup olmadığını kontrol eder.

    - Aralık dışı → reject (valid=False)
    - None/NaN   → reject
    - Geçerli    → valid=True, value=float
    """
    if value is None:
        logger.warning("%s: değer None", name)
        return ValidationResult(valid=False, error=f"{name} verisi yok (None)")

    try:
        val = float(value)
    except (TypeError, ValueError):
        logger.warning("%s: float'a çevrilemedi: %r", name, value)
        return ValidationResult(valid=False, error=f"{name} sayısal değil: {value!r}")

    if pd.isna(val):
        logger.warning("%s: NaN değer", name)
        return ValidationResult(valid=False, error=f"{name} NaN")

    spec = RANGES.get(name)
    if spec is None:
        # Tanımlı aralık yok → geçir
        return ValidationResult(valid=True, value=val)

    lo, hi = spec["min"], spec["max"]
    if not (lo <= val <= hi):
        logger.error("%s = %.4f → aralık dışı [%.2f, %.2f]", name, val, lo, hi)
        return ValidationResult(
            valid=False,
            error=f"{name} = {val:.4f} aralık dışı [{lo}, {hi}]",
        )

    return ValidationResult(valid=True, value=val)


def validate_spot(value) -> ValidationResult:
    """EUR/USD spot değerini doğrular."""
    return validate_range(value, "EUR/USD")


def validate_dxy(value) -> ValidationResult:
    """DXY endeks değerini doğrular."""
    return validate_range(value, "DXY")


def validate_vix(value) -> ValidationResult:
    """VIX endeks değerini doğrular. >40 uyarı üretir."""
    result = validate_range(value, "VIX")
    if result.valid and result.value is not None:
        warn_high = RANGES["VIX"]["warn_high"]
        if result.value > warn_high:
            result.warnings.append(
                f"VIX = {result.value:.1f} > {warn_high} → Yüksek volatilite modu"
            )
            logger.warning("VIX yüksek: %.1f", result.value)
    return result


def validate_yield(value, name: str) -> ValidationResult:
    """Faiz oranı doğrulaması (US2Y, US10Y, DE2Y, DE10Y)."""
    return validate_range(value, name)


# ─────────────────────────────────────────────
# Çapraz doğrulamalar
# ─────────────────────────────────────────────
def validate_yield_curve(us2y, us10y) -> ValidationResult:
    """Yield curve inversiyonu kontrolü.

    US2Y > US10Y ise uyarı üretir (inversion).
    Reject etmez çünkü inversion olabilir ama veri doğrudur.
    """
    warnings = []

    if us2y is None or us10y is None:
        return ValidationResult(valid=True, value=None)

    try:
        v2 = float(us2y)
        v10 = float(us10y)
    except (TypeError, ValueError):
        return ValidationResult(valid=True, value=None)

    if v2 > v10:
        msg = f"Yield curve inversion: US2Y ({v2:.2f}%) > US10Y ({v10:.2f}%)"
        warnings.append(msg)
        logger.info(msg)

    return ValidationResult(valid=True, value={"us2y": v2, "us10y": v10}, warnings=warnings)


# ─────────────────────────────────────────────
# DataFrame doğrulama
# ─────────────────────────────────────────────
def validate_ohlc_dataframe(df, name: str, min_rows: int = 30) -> ValidationResult:
    """OHLC DataFrame doğrulaması.

    Kontroller:
    - None / boş değil
    - Gerekli kolonlar mevcut (Open, High, Low, Close)
    - Minimum satır sayısı
    - NaN oranı kabul edilebilir düzeyde
    """
    if df is None:
        logger.warning("%s: DataFrame None", name)
        return ValidationResult(valid=False, error=f"{name} verisi alınamadı")

    if not isinstance(df, pd.DataFrame):
        logger.warning("%s: DataFrame değil: %s", name, type(df).__name__)
        return ValidationResult(valid=False, error=f"{name} DataFrame değil")

    if df.empty:
        logger.warning("%s: DataFrame boş", name)
        return ValidationResult(valid=False, error=f"{name} verisi boş")

    required_cols = {"Open", "High", "Low", "Close"}
    missing_cols = required_cols - set(df.columns)
    if missing_cols:
        logger.warning("%s: eksik kolonlar: %s", name, missing_cols)
        return ValidationResult(
            valid=False,
            error=f"{name} eksik kolonlar: {missing_cols}",
        )

    if len(df) < min_rows:
        logger.warning("%s: yetersiz veri (%d < %d)", name, len(df), min_rows)
        return ValidationResult(
            valid=False,
            error=f"{name}: {len(df)} satır < minimum {min_rows}",
        )

    warnings = []

    # NaN oranı kontrolü
    nan_pct = df[list(required_cols)].isna().mean().mean() * 100
    if nan_pct > 10:
        warnings.append(f"{name}: NaN oranı yüksek ({nan_pct:.1f}%)")
        logger.warning("%s: NaN oranı %.1f%%", name, nan_pct)

    # Son kapanış mantık kontrolü
    last_close = df["Close"].iloc[-1]
    vr = validate_range(last_close, name)
    if not vr.valid:
        warnings.append(f"{name}: son kapanış geçersiz → {vr.error}")

    return ValidationResult(valid=True, value=df, warnings=warnings)


# ─────────────────────────────────────────────
# Günlük değişim kontrolü
# ─────────────────────────────────────────────
def validate_daily_change(current, previous, name: str, max_pct: float = 5.0) -> ValidationResult:
    """Günlük yüzde değişimin aşırı olup olmadığını kontrol eder.

    >max_pct değişim → uyarı (reject değil, çünkü flash crash gerçek olabilir).
    """
    if current is None or previous is None:
        return ValidationResult(valid=True, value=None)

    try:
        cur = float(current)
        prev = float(previous)
    except (TypeError, ValueError):
        return ValidationResult(valid=True, value=None)

    if prev == 0:
        return ValidationResult(valid=True, value=cur)

    pct_change = abs((cur / prev - 1) * 100)

    warnings = []
    if pct_change > max_pct:
        msg = f"{name}: günlük değişim %{pct_change:.2f} > %{max_pct} → aşırı hareket"
        warnings.append(msg)
        logger.warning(msg)

    return ValidationResult(valid=True, value=cur, warnings=warnings)


# ─────────────────────────────────────────────
# Veri tazelik kontrolü
# ─────────────────────────────────────────────
def validate_freshness(fetched_at: Optional[datetime]) -> ValidationResult:
    """Verinin ne kadar güncel olduğunu kontrol eder.

    Returns:
        ValidationResult with value = "fresh" | "warning" | "stale"
    """
    if fetched_at is None:
        return ValidationResult(
            valid=True,
            value="stale",
            warnings=["Veri zamanı bilinmiyor"],
        )

    now = datetime.now(timezone.utc)

    # Ensure timezone-aware
    if fetched_at.tzinfo is None:
        fetched_at = fetched_at.replace(tzinfo=timezone.utc)

    age_seconds = (now - fetched_at).total_seconds()

    if age_seconds < 0:
        # Future timestamp → accept as fresh
        return ValidationResult(valid=True, value="fresh")

    if age_seconds <= FRESHNESS_FRESH:
        return ValidationResult(valid=True, value="fresh")

    if age_seconds <= FRESHNESS_WARNING:
        return ValidationResult(
            valid=True,
            value="warning",
            warnings=[f"Veri {age_seconds/60:.0f} dakika eski"],
        )

    return ValidationResult(
        valid=True,
        value="stale",
        warnings=[f"Veri {age_seconds/60:.0f} dakika eski → güncelleme önerilir"],
    )


# ─────────────────────────────────────────────
# Bundle-level toplu doğrulama
# ─────────────────────────────────────────────
def validate_market_bundle(bundle: dict) -> dict:
    """get_market_bundle() çıktısını toplu olarak doğrular.

    Returns:
        Original bundle enriched with validation metadata so engine can
        keep using the market fields directly.
    """
    results = {}
    all_warnings = []
    all_errors = []

    # Spot
    r = validate_spot(bundle.get("spot"))
    results["spot"] = r
    all_warnings.extend(r.warnings)
    if r.error:
        all_errors.append(r.error)

    # DXY yüzde değişim
    dxy_pct = bundle.get("dxy_pct")
    if dxy_pct is not None:
        r = ValidationResult(valid=True, value=dxy_pct)
        if abs(dxy_pct) > RANGES["DXY"]["warn_3d_pct"]:
            r.warnings.append(f"DXY 3G değişim = %{dxy_pct:.2f} → aşırı hareket")
        results["dxy_pct"] = r
        all_warnings.extend(r.warnings)

    # VIX
    r = validate_vix(bundle.get("vix"))
    results["vix"] = r
    all_warnings.extend(r.warnings)
    if r.error:
        all_errors.append(r.error)

    # Faiz oranları
    for key in ["us2y", "us10y", "de2y", "de10y"]:
        name_map = {"us2y": "US2Y", "us10y": "US10Y", "de2y": "DE2Y", "de10y": "DE10Y"}
        r = validate_yield(bundle.get(key), name_map[key])
        results[key] = r
        all_warnings.extend(r.warnings)
        if r.error:
            all_errors.append(r.error)

    # Yield curve inversion
    r = validate_yield_curve(bundle.get("us2y"), bundle.get("us10y"))
    results["yield_curve"] = r
    all_warnings.extend(r.warnings)

    # OHLC DataFrames
    for df_key, name, min_rows in [
        ("eur_1d", "EUR/USD", 100),
        ("eur_4h", "EUR/USD_4H", 30),
        ("dxy_df", "DXY", 60),
        ("vix_df", "VIX", 60),
    ]:
        r = validate_ohlc_dataframe(bundle.get(df_key), name, min_rows)
        results[df_key] = r
        all_warnings.extend(r.warnings)
        if r.error:
            all_errors.append(r.error)

    # Kritik veri mevcut mu?
    # EUR/USD 1D olmadan EDE hesaplanamaz
    critical_ok = results.get("eur_1d", ValidationResult(valid=False)).valid

    summary = {
        "valid": critical_ok,
        "warning_count": len(all_warnings),
        "error_count": len(all_errors),
        "warnings": all_warnings,
        "errors": all_errors,
    }

    return {
        **bundle,
        "validation_results": results,
        "validation_flags": all_warnings + all_errors,
        "validation_summary": summary,
    }
