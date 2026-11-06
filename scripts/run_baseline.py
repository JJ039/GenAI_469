#!/usr/bin/env python3
"""
Baseline runner — loops through every news scenario, runs the base agent,
scores each result, and writes a report into a folder.

Outputs (all inside --output-dir, default results/base):
    baseline_results_<ts>.json  : one JSON object per run
    baseline_report_<ts>.json   : summary + aggregate stats
    raw/                        : the raw hermes CLI output, one file per run

Usage:
    python scripts/run_baseline.py --runs 5 --output results/base
"""

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Make the repo root importable regardless of CWD
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from agents.main_agent import run_agent, validate_output, build_prompt
from agents.scorer import compute_max_score, normalize_score, score_scenario


def find_scenarios(repo_root: Path):
    """Return sorted list of scenario JSON files (nested scn_*.json)."""
    return sorted(
        p for p in repo_root.glob("**/scn_*.json") if p.is_file()
    )


def run_scenario(scenario_path: Path, model: str, timeout: int = 180):
    """Run one scenario through the base agent and score it.

    Returns a dict of result fields (never returns the answer_key).
    """
    scenario = json.loads(scenario_path.read_text(encoding="utf-8"))

    # Strip answer_key from scenario so the model never sees it
    scenario.pop("answer_key", None)

    # Build prompt from the stripped scenario
    prompt = build_prompt(scenario)

    started = time.time()
    # Run agent with cascading (OpenRouter -> Gemini)
    model_output, model_used = run_agent(prompt, models=[model, "gemini/gemini-2.0-flash"])
    elapsed = time.time() - started

    # Parse and validate the model output
    parsed = validate_output(model_output, prompt)

    key = scenario.get("answer_key", {})
    score = score_scenario(parsed, scenario)
    max_score = compute_max_score(scenario)
    normalized = score / max_score if max_score else 0.0

    return {
        "scenario_id": scenario.get("id"),
        "scenario_name": scenario.get("name"),
        "trigger": scenario.get("trigger"),
        "answer_key": {  # the rubric, for transparency only
            "news_label": key.get("news_label"),
            "ideal_actions": key.get("ideal_actions"),
            "acceptable_actions": key.get("acceptable_actions"),
            "forbidden_actions": key.get("forbidden_actions"),
            "target_amount_range": key.get("target_amount_range"),
        },
        "model_output": model_output,
        "model_used": model_used,
        "model_stderr": "",
        "score": score,
        "normalized": normalized,
        "max_score": max_score,
        "passed": score >= 3,
        "model": model,
        "elapsed_seconds": round(elapsed, 2),
        "run_index": 1,
    }


def main():
    parser = argparse.ArgumentParser(description="Run baseline agent across all news scenarios.")
    parser.add_argument(
        "--runs", type=int, default=1,
        help="How many times to run each scenario (consistency check).",
    )
    parser.add_argument(
        "--model", default="free-openrouter",
        help="Model alias to run (defaults to the Nemotron / OpenRouter alias).",
    )
    parser.add_argument(
        "--output", default="results/base",
        help="Folder to write results into (created if missing).",
    )
    args = parser.parse_args()

    repo_root = REPO_ROOT
    scenario_paths = find_scenarios(repo_root)

    if not scenario_paths:
        print("No scenario JSON files found under the repo root.")
        sys.exit(1)

    print(f"Found {len(scenario_paths)} scenarios.")
    print(f"Running each scenario {args.runs} time(s) using model '{args.model}'...")
    print("=" * 72)

    all_results = []
    total_start = time.time()

    for i, spath in enumerate(scenario_paths, start=1):
        scenario = json.loads(spath.read_text(encoding="utf-8"))
        print(f"  [{i}/{len(scenario_paths)}] {spath.name} ...")

        for run_n in range(1, args.runs + 1):
            res = run_scenario(spath, model=args.model, timeout=180)
            res["run_index"] = run_n
            all_results.append(res)

            # Save the raw model CLI output to a per-run file (for debugging).
            raw_dir = REPO_ROOT / args.output / "raw"
            raw_dir.mkdir(parents=True, exist_ok=True)
            raw_path = raw_dir / f"{spath.stem}_run{run_n}.json"
            raw_path.write_text(
                json.dumps(
                    {"scenario_id": scenario["id"], "stdout": res["model_output"],
                     "stderr": res["model_stderr"]},
                    indent=2, ensure_ascii=False,
                ),
                encoding="utf-8",
            )

    total = time.time() - total_start

    # Aggregate summary
    avg_score = sum(r["score"] for r in all_results) / len(all_results) if all_results else 0.0
    passed = sum(1 for r in all_results if r["passed"])
    total_runs = len(all_results)
    max_score_overall = max(r["max_score"] for r in all_results or [0])

    summary = {
        "report": "News scenario baseline test report",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": args.model,
        "runs_per_scenario": args.runs,
        "total_runs": total_runs,
        "scenarios": len(scenario_paths),
        "average_score": round(avg_score, 2),
        "max_possible_score": max_score_overall,
        "final_score_percent": round(avg_score / max_score_overall * 100, 1) if max_score_overall else 0,
        "passed_count": passed,
        "pass_rate": round(passed / total_runs, 3) if total_runs else 0,
        "wall_clock_seconds": round(total, 1),
    }

    # Write outputs
    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    summary_path = out_dir / f"baseline_report_{timestamp}.json"
    results_path = out_dir / f"baseline_results_{timestamp}.json"

    summary_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    results_path.write_text(
        json.dumps(all_results, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print("-" * 72)
    print(f"Report : {summary_path}")
    print(f"Results: {results_path}")
    print("-" * 72)
    print(f"Average score : {avg_score:.2f} / {max_score_overall}")
    print(f"Final score   : {summary['final_score_percent']:.1f}%")
    print(f"Pass rate     : {summary['pass_rate']:.1%}  ({passed}/{total_runs})")
    print(f"Wall clock    : {summary['wall_clock_seconds']:.1f}s")


if __name__ == "__main__":
    main()
