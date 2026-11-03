#!/usr/bin/env python3
"""
Test runner: runs the base agent on all scenarios and scores the results.
Saves raw outputs and summary scores to results/base/<timestamp>/
"""
import json
import os
import sys
import subprocess
from datetime import datetime

# Add agents directory to path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE_DIR, "agents"))

# Import the agent modules
from main_agent import build_prompt, run_agent, validate_output
from scorer import score_scenario, compute_max_score, normalize_score

# Paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCENARIOS_DIR = os.path.join(BASE_DIR, "scenarios", "scenarios")
RESULTS_DIR = os.path.join(BASE_DIR, "results", "base")
AGENT_SCRIPT = os.path.join(BASE_DIR, "agents", "main_agent.py")

# Get timestamp for output folder
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
OUTPUT_DIR = os.path.join(RESULTS_DIR, timestamp)
RAW_DIR = os.path.join(OUTPUT_DIR, "raw")
SUMMARY_FILE = os.path.join(OUTPUT_DIR, "summary.json")

# Ensure directories exist
os.makedirs(RAW_DIR, exist_ok=True)

# Load scenario files
scenario_files = sorted([
    f for f in os.listdir(SCENARIOS_DIR)
    if f.endswith(".json") and not f.startswith("scenario")
])

print(f"Found {len(scenario_files)} scenarios")
print(f"Output directory: {OUTPUT_DIR}")
print()

# Run each scenario
results = []
for scenario_file in scenario_files:
    scenario_path = os.path.join(SCENARIOS_DIR, scenario_file)
    scenario = json.load(open(scenario_path))
    
    print(f"Running scenario: {scenario_file}...")
    
    # Build the prompt using the agent's build_prompt function
    prompt = build_prompt(scenario)
    
    # Add explicit JSON-only instruction
    prompt += '\n\nIMPORTANT: Your entire response must be ONLY a valid JSON object. No conversational text, no explanations, no markdown. Just the JSON.'
    
    # Run the agent
    model_output = run_agent(prompt)
    
    # Validate and parse the output (this handles JSON extraction)
    parsed = validate_output(model_output, prompt)
    
    if parsed:
        run_data = {"scenario": scenario_file, "raw_output": model_output, "parsed": parsed}
    else:
        run_data = {"scenario": scenario_file, "raw_output": model_output, "parsed": {}}
    
    # Score the output
    score = score_scenario(run_data.get("parsed", {}), scenario)
    max_score = compute_max_score(scenario)
    normalized = normalize_score(score, scenario)
    
    run_data["score"] = score
    run_data["max_score"] = max_score
    run_data["normalized_score"] = normalized
    run_data["status"] = "PASS" if normalized >= 0.6 else "FAIL"
    
    results.append(run_data)
    
    # Save raw output
    raw_file = os.path.join(RAW_DIR, f"{scenario_file.replace('.json', '_run1.json')}")
    with open(raw_file, "w") as f:
        json.dump(run_data, f, indent=2)
    
    print(f"  Score: {score}/{max_score} ({normalized:.2%}) - {run_data['status']}")
    print(f"  Parsed: {run_data.get('parsed', {})}")

# Save summary
summary = {
    "timestamp": timestamp,
    "total_scenarios": len(results),
    "total_runs": len(results),  # 1 run per scenario in this script
    "results": results,
    "aggregate": {
        "avg_score": sum(r["score"] for r in results) / len(results),
        "avg_normalized": sum(r["normalized_score"] for r in results) / len(results),
        "pass_count": sum(1 for r in results if r["status"] == "PASS"),
        "fail_count": sum(1 for r in results if r["status"] == "FAIL"),
    }
}

with open(SUMMARY_FILE, "w") as f:
    json.dump(summary, f, indent=2)

print()
print("=" * 50)
print(f"Summary: {summary['aggregate']['pass_count']} PASS, {summary['aggregate']['fail_count']} FAIL")
print(f"Average normalized score: {summary['aggregate']['avg_normalized']:.2%}")
print(f"Output saved to: {OUTPUT_DIR}")
