from __future__ import annotations

import json
from pathlib import Path

from backend.entrypoint import answer_question


def run_dataset(path: str = "backend/evals/demo_prompts.jsonl", *, use_langgraph: bool = False) -> list[dict]:
    results = []
    p = Path(path)
    if not p.exists():
        return results

    for raw in p.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        item = json.loads(raw)
        out = answer_question(item["question"], use_langgraph=use_langgraph)
        results.append(
            {
                "question": item["question"],
                "expected_mode": item.get("expected_mode"),
                "actual_mode": out.get("mode"),
                "pass": out.get("mode") == item.get("expected_mode"),
                "debug": out.get("debug"),
            }
        )
    return results


if __name__ == "__main__":
    res = run_dataset()
    passed = sum(1 for item in res if item["pass"])
    print(json.dumps({"total": len(res), "passed": passed, "results": res}, indent=2))
