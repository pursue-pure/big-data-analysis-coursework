from __future__ import annotations

import json
import sys
from pathlib import Path

from fastapi.testclient import TestClient


ROOT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT_DIR))

from dashboard.server import app  # noqa: E402


def main() -> None:
    output_dir = ROOT_DIR / "output"
    output_dir.mkdir(exist_ok=True)

    client = TestClient(app)
    checks = {
        "health": client.get("/api/health").json(),
        "system_status": client.get("/api/system-status").json(),
        "stats_all": client.get("/api/stats").json(),
        "stats_negative": client.get("/api/stats", params={"sentiment": "负面"}).json(),
        "regex_reviews": client.get(
            "/api/reviews",
            params={"cat": "手机", "sentiment": "负面", "query": "[差烂]", "limit": 3},
        ).json(),
        "invalid_regex_fallback": client.get("/api/reviews", params={"query": "[", "limit": 3}).json(),
        "scatter_negative": client.get(
            "/api/scatter-points",
            params={"sentiment": "负面", "limit": 120},
        ).json(),
    }

    summary = {
        "input_data_source": checks["health"]["data_source"],
        "rows": checks["health"]["rows"],
        "categories": checks["health"]["categories"],
        "system_status": checks["system_status"]["status"],
        "llm_active": checks["system_status"]["llm"]["llm_active"],
        "llm_reason": checks["system_status"]["llm"]["reason"],
        "data_degraded": checks["system_status"]["data"]["data_degraded"],
        "all_rows_from_stats": checks["stats_all"]["rows"],
        "negative_rows": checks["stats_negative"]["rows"],
        "regex_phone_negative_total": checks["regex_reviews"]["total"],
        "regex_query_mode": checks["regex_reviews"]["query_mode"],
        "invalid_regex_query_mode": checks["invalid_regex_fallback"]["query_mode"],
        "scatter_negative_total": checks["scatter_negative"]["total"],
        "scatter_negative_sampled": checks["scatter_negative"]["sampled"],
        "checks": checks,
    }

    out_path = output_dir / "system_validation_week14.json"
    out_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "checks"}, ensure_ascii=False, indent=2))
    print(f"saved: {out_path}")


if __name__ == "__main__":
    main()
