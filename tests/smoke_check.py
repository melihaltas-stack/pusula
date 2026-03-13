import json
import os
import sys


def main():
    os.environ.setdefault("SELVESE_CACHE_NAMESPACE", "prod")

    root = "/Users/melihaltas/Desktop/Pusula"
    if root not in sys.path:
        sys.path.insert(0, root)

    from engine import run_engine

    result = run_engine()

    summary = {
        "error": result.get("error"),
        "ede": result.get("ede"),
        "karar": result.get("karar"),
        "data_quality": result.get("data_quality"),
        "validation_summary": result.get("validation_summary"),
        "dxy_source": result.get("dxy_source"),
        "us2y_source": result.get("us2y_source"),
        "us10y_source": result.get("us10y_source"),
    }
    print(json.dumps(summary, ensure_ascii=False, default=str, indent=2))

    if result.get("error"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
