"""Probability calibration helpers."""

from typing import Iterable


def brier_score(probabilities: Iterable[float], outcomes: Iterable[float]) -> float:
    pairs = [
        ((float(p) / 100.0) if float(p) > 1 else float(p), float(y))
        for p, y in zip(probabilities, outcomes)
    ]
    if not pairs:
        return 0.0
    return round(sum((p - y) ** 2 for p, y in pairs) / len(pairs), 4)


def calibration_buckets(probabilities: Iterable[float], outcomes: Iterable[float], bucket_size: int = 10) -> list:
    buckets = []
    pairs = [
        ((float(p) / 100.0) if float(p) > 1 else float(p), float(y))
        for p, y in zip(probabilities, outcomes)
    ]
    if not pairs:
        return buckets

    for bucket_start in range(0, 100, bucket_size):
        lo = bucket_start / 100.0
        hi = (bucket_start + bucket_size) / 100.0
        bucket_pairs = [(p, y) for p, y in pairs if lo <= p < hi or (bucket_start == 90 and p <= 1.0)]
        if not bucket_pairs:
            continue
        avg_prob = sum(p for p, _ in bucket_pairs) / len(bucket_pairs)
        hit_rate = sum(y for _, y in bucket_pairs) / len(bucket_pairs)
        buckets.append(
            {
                "bucket": f"{bucket_start}-{bucket_start + bucket_size}",
                "avg_probability": round(avg_prob * 100, 1),
                "actual_hit_rate": round(hit_rate * 100, 1),
                "gap": round((hit_rate - avg_prob) * 100, 1),
                "count": len(bucket_pairs),
            }
        )
    return buckets


def summarize_calibration(probabilities: Iterable[float], outcomes: Iterable[float]) -> dict:
    probs = list(probabilities)
    ys = list(outcomes)
    buckets = calibration_buckets(probs, ys)
    if not buckets:
        return {
            "brier": 0.0,
            "buckets": [],
            "avg_abs_gap": 0.0,
            "summary": "Calibration için yeterli veri yok.",
        }

    avg_abs_gap = round(sum(abs(bucket["gap"]) for bucket in buckets) / len(buckets), 1)
    brier = brier_score(probs, ys)
    summary = f"Brier {brier:.3f} | Ortalama calibration gap %{avg_abs_gap:.1f}"
    return {
        "brier": brier,
        "buckets": buckets,
        "avg_abs_gap": avg_abs_gap,
        "summary": summary,
    }
