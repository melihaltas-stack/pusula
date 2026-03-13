"""
freshness.py
------------
Selvese EUR Satış Pusulası — Veri Tazelik Sistemi

Her veri kaynağı için:
  - fetched_at timestamp kaydı
  - TTL eşiklerine göre fresh / warning / stale etiketleme
  - UI için renk kodlu badge üretimi
  - Bundle genelinde özet tazelik skoru

Eşikler (roadmap Faz 1 uyumlu):
  Kaynak          Cache TTL   warning eşiği   stale eşiği
  ─────────────────────────────────────────────────────────
  Spot / OHLCV    60 sn       45 sn           60 sn
  Faiz oranları   1800 sn     1500 sn         1800 sn
  Makro takvim    3600 sn     3000 sn         3600 sn
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tipler
# ---------------------------------------------------------------------------

FreshnessLabel = Literal["fresh", "warning", "stale", "unknown"]


@dataclass
class FreshnessStatus:
    label: FreshnessLabel
    age_seconds: float | None       # None → fetched_at bilinmiyor
    fetched_at: datetime | None
    source_key: str
    ttl_warning: int                # saniye
    ttl_stale: int                  # saniye

    @property
    def color(self) -> str:
        return {
            "fresh":   "#00c389",
            "warning": "#f59e0b",
            "stale":   "#ef4444",
            "unknown": "#64748b",
        }[self.label]

    @property
    def badge_emoji(self) -> str:
        return {
            "fresh":   "🟢",
            "warning": "🟡",
            "stale":   "🔴",
            "unknown": "⚪",
        }[self.label]

    @property
    def age_text(self) -> str:
        if self.age_seconds is None:
            return "bilinmiyor"
        if self.age_seconds < 60:
            return f"{int(self.age_seconds)}sn"
        return f"{int(self.age_seconds // 60)}dk {int(self.age_seconds % 60)}sn"

    def __str__(self) -> str:
        return f"{self.badge_emoji} {self.source_key}: {self.label} ({self.age_text})"


# ---------------------------------------------------------------------------
# TTL tanımları
# ---------------------------------------------------------------------------

# (warning_sn, stale_sn)
_TTL_RULES: dict[str, tuple[int, int]] = {
    "spot":         (45,   60),
    "eur_1d":       (45,   60),
    "eur_4h":       (45,   60),
    "dxy_df":       (45,   60),
    "vix_df":       (45,   60),
    "us2y":         (1500, 1800),
    "us10y":        (1500, 1800),
    "de2y":         (1500, 1800),
    "de10y":        (1500, 1800),
    "macro_events": (3000, 3600),
}

_DEFAULT_TTL = (270, 300)   # bilinmeyen kaynaklar için


# ---------------------------------------------------------------------------
# Yardımcı: şu anki UTC zamanı
# ---------------------------------------------------------------------------

def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Timestamp kayıt fonksiyonu
# ---------------------------------------------------------------------------

def stamp(source_key: str) -> datetime:
    """Şu anki UTC zamanını döner. Veri çekildiğinde kaydedilmek üzere."""
    ts = _now_utc()
    logger.debug("freshness.stamp: %s fetched_at=%s", source_key, ts.isoformat())
    return ts


# ---------------------------------------------------------------------------
# Tazelik hesaplama
# ---------------------------------------------------------------------------

def check(source_key: str, fetched_at: datetime | None) -> FreshnessStatus:
    """
    Tek bir kaynak için tazelik durumu hesapla.

    Parameters
    ----------
    source_key  : TTL kurallarında tanımlı anahtar (ör. "us2y")
    fetched_at  : Verinin çekildiği UTC datetime (None → unknown)
    """
    ttl_w, ttl_s = _TTL_RULES.get(source_key, _DEFAULT_TTL)

    if fetched_at is None:
        return FreshnessStatus(
            label="unknown",
            age_seconds=None,
            fetched_at=None,
            source_key=source_key,
            ttl_warning=ttl_w,
            ttl_stale=ttl_s,
        )

    # timezone-aware karşılaştırma
    if fetched_at.tzinfo is None:
        fetched_at = fetched_at.replace(tzinfo=timezone.utc)

    age = (_now_utc() - fetched_at).total_seconds()

    if age >= ttl_s:
        label: FreshnessLabel = "stale"
    elif age >= ttl_w:
        label = "warning"
    else:
        label = "fresh"

    if label != "fresh":
        logger.warning(
            "freshness.check: %s %s (age=%.0fsn, stale_at=%dsn)",
            source_key, label, age, ttl_s,
        )

    return FreshnessStatus(
        label=label,
        age_seconds=age,
        fetched_at=fetched_at,
        source_key=source_key,
        ttl_warning=ttl_w,
        ttl_stale=ttl_s,
    )


# ---------------------------------------------------------------------------
# Bundle tazelik özeti
# ---------------------------------------------------------------------------

@dataclass
class BundleFreshness:
    statuses: dict[str, FreshnessStatus] = field(default_factory=dict)

    @property
    def worst_label(self) -> FreshnessLabel:
        priority = {"stale": 3, "warning": 2, "fresh": 1, "unknown": 0}
        if not self.statuses:
            return "unknown"
        return max(self.statuses.values(), key=lambda s: priority[s.label]).label

    @property
    def score(self) -> float:
        """0-100 arası tazelik skoru. 100 = tümü fresh."""
        if not self.statuses:
            return 0.0
        label_score = {"fresh": 100, "warning": 60, "stale": 0, "unknown": 40}
        return round(sum(label_score[s.label] for s in self.statuses.values()) / len(self.statuses), 1)

    @property
    def summary_text(self) -> str:
        counts = {"fresh": 0, "warning": 0, "stale": 0, "unknown": 0}
        for s in self.statuses.values():
            counts[s.label] += 1
        parts = []
        if counts["stale"]:
            parts.append(f"🔴 {counts['stale']} eski")
        if counts["warning"]:
            parts.append(f"🟡 {counts['warning']} uyarı")
        if counts["fresh"]:
            parts.append(f"🟢 {counts['fresh']} taze")
        return " · ".join(parts) if parts else "Veri tazeliği bilinmiyor"

    def stale_keys(self) -> list[str]:
        return [k for k, s in self.statuses.items() if s.label == "stale"]

    def warning_keys(self) -> list[str]:
        return [k for k, s in self.statuses.items() if s.label == "warning"]


def build_bundle_freshness(timestamps: dict[str, datetime | None]) -> BundleFreshness:
    """
    Bundle içindeki tüm kaynaklar için tazelik hesapla.

    Parameters
    ----------
    timestamps : {source_key: fetched_at datetime | None}
    """
    statuses = {key: check(key, ts) for key, ts in timestamps.items()}
    bf = BundleFreshness(statuses=statuses)

    if bf.worst_label in ("stale", "warning"):
        logger.warning(
            "build_bundle_freshness: %s — stale=%s warning=%s",
            bf.summary_text,
            bf.stale_keys(),
            bf.warning_keys(),
        )

    return bf
