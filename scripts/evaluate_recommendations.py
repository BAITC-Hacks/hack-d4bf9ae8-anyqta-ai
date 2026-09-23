#!/usr/bin/env python3
"""Compare recommendations on synthetic holdout scenarios; live AI is opt-in."""

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.career import calculate_trajectory
from backend.app.db import connect
from backend.app.importer import import_package, load_full_package, load_profile_package
from backend.app.recommendations import eligible_candidates, recommend_employee, selector_from_environment


def evaluate(with_ai=False):
    selector = selector_from_environment() if with_ai else None
    if with_ai and selector is None:
        raise ValueError("AI evaluation requires configured LLM_API_URL, LLM_API_KEY and LLM_MODEL")
    expectations = json.loads((ROOT / "examples/jury/expectations.json").read_text())
    rows = []
    with tempfile.TemporaryDirectory() as directory:
        connection = connect(Path(directory) / "evaluation.db")
        try:
            import_package(connection, load_full_package(ROOT / "data/career_quest_dataset"), "full", "bundled")
            import_package(connection, load_profile_package(ROOT / "examples/jury/employees.json", ROOT / "examples/jury/activity_history.csv"), "profiles", "evaluation")
            for case in expectations:
                employee_id = case["employee_id"]
                candidates = eligible_candidates(connection, employee_id)
                gaps = [gap for gap in calculate_trajectory(connection, employee_id)["skill_gaps"] if gap["gap"] > 0]
                weakest = min(gaps, key=lambda gap: (gap["current_level"], gap["skill_id"]))["skill_id"]
                naive = sorted((candidate for candidate in candidates if any(
                    change["skill_id"] == weakest and change["target_gap_reduction"] > 0 for change in candidate.skill_changes
                )), key=lambda item: item.event_id)
                rows.append({"employee_id": employee_id, "method": "minimum_skill",
                             "top1_acceptable": bool(naive and naive[0].event_id in case["acceptable_first"]),
                             "event_ids": [naive[0].event_id] if naive else []})
                for method, model in [("rules", None)] + ([("live_ai", selector)] if with_ai else []):
                    start = time.perf_counter()
                    result = recommend_employee(connection, employee_id, selector=model)
                    ids = [item["event_id"] for item in result["recommendations"]]
                    rows.append({"employee_id": employee_id, "method": method, "mode": result["mode"],
                                 "top1_acceptable": bool(ids and ids[0] in case["acceptable_first"]),
                                 "all_eligible": set(ids) <= {item.event_id for item in candidates},
                                 "no_forbidden": not set(ids).intersection(case["forbidden"]),
                                 "fact_evidence": all(len(item["evidence"]) >= 2 and item["expected_skill_changes"] for item in result["recommendations"]),
                                 "seconds": round(time.perf_counter() - start, 3), "event_ids": ids})
        finally:
            connection.close()
    methods = sorted({row["method"] for row in rows})
    return {"scope": "Three authored synthetic cases, not the hidden jury profiles or proof of general model quality.",
            "live_ai_tested": with_ai,
            "summary": {method: {"acceptable_first": sum(row["top1_acceptable"] for row in rows if row["method"] == method), "cases": len(expectations)} for method in methods},
            "cases": rows}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--with-ai", action="store_true", help="Call the configured provider (may incur API charges)")
    args = parser.parse_args()
    result = evaluate(args.with_ai)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    failures = [row for row in result["cases"] if row["method"] != "minimum_skill" and
                (not all(row.get(key, False) for key in ("top1_acceptable", "all_eligible", "no_forbidden", "fact_evidence"))
                 or row["seconds"] >= 10 or (row["method"] == "live_ai" and row["mode"] != "llm"))]
    raise SystemExit(bool(failures))
