import argparse
import pickle
import sys
import time
from datetime import datetime
from pathlib import Path


ROOT = Path("/Users/melihaltas/Desktop/Pusula")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine import run_engine  # noqa: E402


DETAIL_CACHE_FILE = Path("/tmp/selvese-pusula-detail-report.pkl")


def load_cache():
    if not DETAIL_CACHE_FILE.exists():
        return None
    try:
        with DETAIL_CACHE_FILE.open("rb") as fh:
            payload = pickle.load(fh)
        if not isinstance(payload, dict):
            return None
        return payload
    except (OSError, pickle.PickleError, EOFError, AttributeError, ValueError):
        return None


def save_cache(result, session_label):
    payload = {
        "saved_at": time.time(),
        "saved_on": datetime.now().strftime("%Y-%m-%d"),
        "session_label": session_label,
        "result": result,
    }
    with DETAIL_CACHE_FILE.open("wb") as fh:
        pickle.dump(payload, fh)


def should_skip(existing_payload, session_label):
    if not existing_payload:
        return False
    return (
        existing_payload.get("saved_on") == datetime.now().strftime("%Y-%m-%d")
        and existing_payload.get("session_label") == session_label
    )


def main():
    parser = argparse.ArgumentParser(description="Generate or refresh detailed Pusula report cache.")
    parser.add_argument("--session", required=True, choices=["eu_open_plus_1h", "us_close_plus_30m"])
    args = parser.parse_args()

    existing = load_cache()
    if should_skip(existing, args.session):
        print(f"skip: detail report already generated for session={args.session}")
        return 0

    result = run_engine(include_extended_data=True, include_performance_report=True)
    if result.get("error"):
        print(f"error: {result['error']}")
        return 1

    save_cache(result, args.session)
    print(f"ok: detail report generated for session={args.session} ede={result.get('ede')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
