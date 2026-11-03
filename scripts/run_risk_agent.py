
#!/usr/bin/env python3
"""
Risk Agent runner — loops through every scenario, runs the
Hermes-powered Risk Agent, scores each result, and writes reports.

Outputs (inside --output-dir, default results/risk_agent):
    risk_agent_results_<ts>.json
    risk_agent_report_<ts>.json
    raw/                         Raw Risk Agent output per run

Usage:
    python scripts/run_risk_agent.py --runs 5
    python scripts/run_risk_agent.py --runs 5 --output results/risk_agent

Requirements:
    - risk_agent_hermes.py in repository root
    - agents/scorer.py
    - Hermes API environment variables configured
"""

import argparse
import json
import sys
import time

from datetime import datetime, timezone
from pathlib import Path


# ============================================================
# 1. MAKE REPOSITORY ROOT IMPORTABLE
# ============================================================

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


# Import the Hermes-powered Risk Agent
from agents.risk_agent import run_risk_agent

# Reuse the existing scoring functions
from agents.scorer import (
    compute_max_score,
    score_scenario,
)


# ============================================================
# 2. FIND SCENARIOS
# ============================================================

def find_scenarios(repo_root: Path):
    """
    Find all scenario JSON files.

    Excludes generated result files and answer-key files.
    """

    return sorted(
        p for p in repo_root.glob("**/scn_*.json")
        if p.is_file()
        and "results" not in p.parts
    )


# ============================================================
# 3. NORMALISE RISK AGENT OUTPUT
# ============================================================

def normalise_risk_output(risk_output):
    """
    Convert the Risk Agent's structured output into the
    common scoring format used by the project.

    IMPORTANT:
    The Risk Agent does not independently verify news.
    Therefore news_label is left as None rather than invented.
    """

    if not isinstance(risk_output, dict):
        raise ValueError("Risk Agent output must be a dictionary")

    recommendation = risk_output.get(
        "recommendation_from_risk_perspective"
    )

    assessments = risk_output.get("action_assessments", [])

    selected_assessment = None

    # Find the assessment corresponding to the recommendation.
    for assessment in assessments:

        if assessment.get("action_type") == recommendation:

            selected_assessment = assessment

            # Prefer an assessment that passed Python validation.
            if assessment.get("eligible_from_programmed_checks"):
                break

    amount = None

    if selected_assessment:
        amount = selected_assessment.get(
            "amount_m",
            selected_assessment.get("amount")
        )

    return {
        "news_label": None,

        "action": recommendation,

        "amount": amount,

        "confidence": risk_output.get("confidence"),

        "rationale": risk_output.get(
            "recommendation_rationale",
            ""
        ),

        "overall_risk_level": risk_output.get(
            "overall_risk_level"
        ),

        "action_assessments": assessments,

        "hard_constraint_violations": risk_output.get(
            "hard_constraint_violations", []
        ),

        "missing_information": risk_output.get(
            "missing_information", []
        ),

        "execution_authorised": risk_output.get(
            "execution_authorised", False
        )
    }


# ============================================================
# 4. RUN ONE SCENARIO
# ============================================================

def run_scenario(scenario_path: Path):
    """
    Run one scenario through the Hermes Risk Agent.

    The answer key is preserved for scoring but never sent
    to the Risk Agent.
    """

    # Load original scenario, including answer key.
    full_scenario = json.loads(
        scenario_path.read_text(encoding="utf-8")
    )

    # Preserve answer key separately for evaluation.
    answer_key = full_scenario.get("answer_key", {})

    # Create a separate copy without answer key.
    agent_scenario = {
        key: value
        for key, value in full_scenario.items()
        if key != "answer_key"
    }

    started = time.time()

    # Run Hermes-powered Risk Agent.
    raw_result = run_risk_agent(agent_scenario)

    elapsed = time.time() - started

    # The earlier Risk Agent implementation returns:
    # {
    #   "trial_id": "...",
    #   "scenario_id": "...",
    #   "duration_seconds": ...,
    #   "validation": {
    #       "valid": True,
    #       "output": {...}
    #   }
    # }

    validation = raw_result.get("validation", {})

    if not validation.get("valid"):
        raise ValueError(
            "Risk Agent output failed validation: "
            + str(validation.get("errors"))
        )

    risk_output = validation.get("output")

    if not isinstance(risk_output, dict):
        raise ValueError("Missing validated Risk Agent output")

    # Convert into the project's common output structure.
    parsed = normalise_risk_output(risk_output)

    # Score using the FULL scenario.
    # The answer key is available to the scorer,
    # but was not provided to Hermes.
    score = score_scenario(parsed, full_scenario)

    max_score = compute_max_score(full_scenario)

    normalized = (
        score / max_score
        if max_score else 0.0
    )

    return {
        "scenario_id": full_scenario.get("id"),
        "scenario_name": full_scenario.get("name"),
        "trigger": full_scenario.get("trigger"),

        "answer_key": {
            "news_label": answer_key.get("news_label"),
            "ideal_actions": answer_key.get("ideal_actions"),
            "acceptable_actions": answer_key.get("acceptable_actions"),
            "forbidden_actions": answer_key.get("forbidden_actions"),
            "target_amount_range": answer_key.get("target_amount_range"),
        },

        "model_output": risk_output,
        "normalised_output": parsed,

        "trial_id": raw_result.get("trial_id"),

        "model_stderr": "",

        "score": score,
        "normalized": normalized,
        "max_score": max_score,

        "passed": score >= 3,

        "elapsed_seconds": round(elapsed, 2),

        "validation": validation
    }


# ============================================================
# 5. MAIN RUNNER
# ============================================================

def main():

    parser = argparse.ArgumentParser(
        description="Run Hermes Risk Agent across all scenarios."
    )

    parser.add_argument(
        "--runs",
        type=int,
        default=1,
        help="Number of repetitions per scenario."
    )

    parser.add_argument(
        "--output",
        default="results/risk_agent",
        help="Output folder."
    )

    args = parser.parse_args()

    if args.runs < 1:
        parser.error("--runs must be at least 1")

    scenario_paths = find_scenarios(REPO_ROOT)

    if not scenario_paths:
        print("No scenario JSON files found.")
        sys.exit(1)

    print(f"Found {len(scenario_paths)} scenarios.")

    print(
        f"Running each scenario {args.runs} time(s) "
        "using Hermes Risk Agent..."
    )

    print("=" * 72)

    all_results = []

    total_start = time.time()

    # ========================================================
    # RUN EACH SCENARIO
    # ========================================================

    for i, scenario_path in enumerate(scenario_paths, start=1):

        scenario = json.loads(
            scenario_path.read_text(encoding="utf-8")
        )

        print(
            f"[{i}/{len(scenario_paths)}] "
            f"{scenario_path.name}"
        )

        for run_n in range(1, args.runs + 1):

            print(f"    Run {run_n}/{args.runs} ...")

            try:

                result = run_scenario(scenario_path)

                result["run_index"] = run_n

                result["run_status"] = "success"

                all_results.append(result)

                print(
                    f"    Score: {result['score']} / "
                    f"{result['max_score']}"
                )

            except Exception as error:

                print(f"    ERROR: {error}")

                result = {
                    "scenario_id": scenario.get("id"),
                    "scenario_name": scenario.get("name"),
                    "run_index": run_n,
                    "run_status": "failed",
                    "error": str(error),
                    "score": 0,
                    "normalized": 0,
                    "passed": False
                }

                all_results.append(result)

            # Save raw output for debugging.
            raw_dir = (
                REPO_ROOT / args.output / "raw"
            )

            raw_dir.mkdir(
                parents=True,
                exist_ok=True
            )

            raw_path = raw_dir / (
                f"{scenario_path.stem}_run{run_n}.json"
            )

            raw_path.write_text(
                json.dumps(
                    result,
                    indent=2,
                    ensure_ascii=False,
                    default=str
                ),
                encoding="utf-8"
            )

    # ========================================================
    # 6. AGGREGATE RESULTS
    # ========================================================

    total = time.time() - total_start

    successful_results = [
        r for r in all_results
        if r.get("run_status") == "success"
    ]

    total_runs = len(all_results)

    successful_runs = len(successful_results)

    avg_score = (
        sum(r["score"] for r in successful_results)
        / successful_runs
        if successful_runs else 0.0
    )

    passed = sum(
        1 for r in successful_results
        if r["passed"]
    )

    max_score_overall = max(
        (r["max_score"] for r in successful_results),
        default=0
    )

    # ========================================================
    # 7. SUMMARY REPORT
    # ========================================================

    summary = {

        "report": "Hermes Risk Agent evaluation report",

        "generated_at": datetime.now(
            timezone.utc
        ).isoformat(),

        "agent": "Hermes Risk Manager",

        "runs_per_scenario": args.runs,

        "total_scenarios": len(scenario_paths),

        "total_runs": total_runs,

        "successful_runs": successful_runs,

        "failed_runs": total_runs - successful_runs,

        "average_score": round(avg_score, 2),

        "max_possible_score": max_score_overall,

        "final_score_percent": (
            round(
                avg_score / max_score_overall * 100,
                1
            )
            if max_score_overall else 0
        ),

        "passed_count": passed,

        "pass_rate": (
            round(passed / successful_runs, 3)
            if successful_runs else 0
        ),

        "wall_clock_seconds": round(total, 2)
    }

    # ========================================================
    # 8. WRITE REPORTS
    # ========================================================

    out_dir = Path(args.output)

    if not out_dir.is_absolute():
        out_dir = REPO_ROOT / out_dir

    out_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    timestamp = datetime.now(
        timezone.utc
    ).strftime("%Y%m%dT%H%M%SZ")

    summary_path = out_dir / (
        f"risk_agent_report_{timestamp}.json"
    )

    results_path = out_dir / (
        f"risk_agent_results_{timestamp}.json"
    )

    summary_path.write_text(
        json.dumps(
            summary,
            indent=2,
            ensure_ascii=False
        ),
        encoding="utf-8"
    )

    results_path.write_text(
        json.dumps(
            all_results,
            indent=2,
            ensure_ascii=False,
            default=str
        ),
        encoding="utf-8"
    )

    # ========================================================
    # 9. PRINT SUMMARY
    # ========================================================

    print("\n" + "=" * 72)

    print("HERMES RISK AGENT RESULTS")

    print("=" * 72)

    print(f"Report       : {summary_path}")

    print(f"Results      : {results_path}")

    print(f"Average score: {avg_score:.2f}")

    print(
        f"Final score  : "
        f"{summary['final_score_percent']:.1f}%"
    )

    print(
        f"Pass rate    : "
        f"{summary['pass_rate']:.1%}"
    )

    print(
        f"Successful   : {successful_runs}/{total_runs}"
    )

    print(
        f"Wall clock   : {summary['wall_clock_seconds']}s"
    )

    print("=" * 72)


if __name__ == "__main__":
    main()
