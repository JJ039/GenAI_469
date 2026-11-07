from flask import Flask, request, jsonify
from flask_cors import CORS
import json
import os
import sys
import threading
import time

AGENTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend", "agents")
sys.path.insert(0, AGENTS_DIR)
from scorer import score_scenario, compute_max_score

app = Flask(__name__)
CORS(app)

SCENARIOS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend", "scenarios", "scenarios")
task_lock = threading.Lock()
task_result = {}
task_error = None
task_status = "pending"
task_stage = 0
task_trace = []
task_id = 0
task_message = "Waiting to start."
task_stage_started_at = time.monotonic()


def as_number(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def publish_stage(stage, message, trace_entry=None):
    """Publish stage status and trace immediately for the dashboard poller."""
    global task_stage, task_trace, task_message, task_stage_started_at
    with task_lock:
        task_stage = stage
        task_message = message
        task_stage_started_at = time.monotonic()
        if trace_entry is not None:
            task_trace = [*task_trace, trace_entry]


def build_fallback_flow(scenario):
    """Run a transparent, local-only demonstration without invoking any model/API."""
    financials = scenario.get("financials") if isinstance(scenario.get("financials"), dict) else {}
    regulations = scenario.get("regulations") if isinstance(scenario.get("regulations"), dict) else {}
    trigger = str(scenario.get("trigger") or "No trigger provided")

    perceived = {
        "reported_event": trigger,
        "financials": dict(financials),
        "regulations": dict(regulations),
        "verification": "unverified (local fallback does not check external sources)",
        "source_note": "Extracted directly from the selected scenario"
    }

    liquidity = as_number(financials.get("liquidity"))
    daily_withdrawals = as_number(financials.get("daily_withdrawals"))
    forecast = as_number(financials.get("forecast_next_7d"))
    borrowing_limit = as_number(financials.get("borrowing_limit"))
    coverage_days = liquidity / daily_withdrawals if daily_withdrawals > 0 else 0.0
    if coverage_days < 1:
        risk_level = "high"
    elif coverage_days < 3 or liquidity < forecast:
        risk_level = "medium"
    else:
        risk_level = "low"

    # This fallback applies a simple demo rule: unverified rumor plus adequate
    # liquidity means hold; a high liquidity risk uses interbank borrowing,
    # capped by the scenario's borrowing limit.
    if risk_level == "high" and borrowing_limit > 0:
        amount = min(max(0.0, daily_withdrawals * 2 - liquidity), borrowing_limit)
        action = "borrow_interbank" if amount > 0 else "hold_position"
    else:
        amount = 0.0
        action = "hold_position"

    reasoned = {
        "news_label": "unverified",
        "risk_level": risk_level,
        "liquidity_coverage_days": round(coverage_days, 2),
        "candidate_action": action,
        "candidate_amount": round(amount, 2),
        "confidence": 0.55,
        "rationale": "Local fallback rule; no external verification"
    }
    final_action = {
        "news_label": reasoned["news_label"],
        "action": reasoned["candidate_action"],
        "amount": reasoned["candidate_amount"],
        "confidence": reasoned["confidence"],
        "rationale": reasoned["rationale"]
    }
    return perceived, reasoned, final_action


@app.route("/api/scenarios", methods=["GET"])
def list_scenarios():
    import glob
    files = sorted(glob.glob(os.path.join(SCENARIOS_DIR, "*.json")))
    return jsonify({"scenarios": [
        {"id": os.path.basename(f), "name": os.path.basename(f).replace(".json", "")}
        for f in files
    ]})


@app.route("/api/run", methods=["POST"])
def run_agent_endpoint():
    global task_result, task_error, task_status, task_stage, task_trace, task_id, task_message, task_stage_started_at
    data = request.get_json(silent=True) or {}
    scenario_file = data.get("scenario")
    if not scenario_file or os.path.basename(scenario_file) != scenario_file or not scenario_file.endswith(".json"):
        return jsonify({"error": "Choose a valid scenario file."}), 400
    scenario_path = os.path.join(SCENARIOS_DIR, scenario_file)
    if not os.path.isfile(scenario_path):
        return jsonify({"error": "Scenario not found."}), 404
    with open(scenario_path, encoding="utf-8") as f:
        scenario = json.load(f)

    with task_lock:
        if task_status == "running":
            return jsonify({"error": "A fallback run is already in progress."}), 409
        task_id += 1
        run_id = str(task_id)
        task_result = {}
        task_error = None
        task_stage = 1
        task_trace = []
        task_status = "running"
        task_message = "Local fallback mode: no model or API call. Reading scenario fields for Perceive."
        task_stage_started_at = time.monotonic()

    def run_fallback_async():
        global task_result, task_error, task_status, task_message
        try:
            # Stage 1: perceive the scenario data locally.
            task_input = {
                "trigger": scenario.get("trigger"),
                "financials": scenario.get("financials", {}),
                "regulations": scenario.get("regulations", {})
            }
            # Build the actual prompt that would be sent to the model (like main_agent.py build_prompt)
            perceive_prompt = f"""You are Hermes, a decision-making AI for a bank.
The following scenario just happened:

{scenario.get('trigger', 'No trigger provided')}

Here are the bank's current financials:
- Capital: {scenario.get('financials', {}).get('capital', 'N/A')}
- Liquidity: {scenario.get('financials', {}).get('liquidity', 'N/A')}
- Borrowing Limit: {scenario.get('financials', {}).get('borrowing_limit', 'N/A')}
- Daily Withdrawals: {scenario.get('financials', {}).get('daily_withdrawals', 'N/A')}
- Forecast Next 7 Days: {scenario.get('financials', {}).get('forecast_next_7d', 'N/A')}

Here are the relevant regulations:
- Max Draw Facility: {scenario.get('regulations', {}).get('max_draw_facility', 'N/A')}
- Report to Regulator: {scenario.get('regulations', {}).get('report_to_regulator', 'N/A')}
- Max Drawal Rate: {scenario.get('regulations', {}).get('max_drawal_rate_pct', 'N/A')}%

Please make a decision in JSON format. Your ENTIRE response must be ONLY the JSON object with these exact fields:
- news_label: "unverified" | "false" | "credible"
- action: "draw_central_bank_facility" | "borrow_interbank" | "hold"
- amount: a number
- confidence: a number between 0.0 and 1.0
- rationale: a short sentence (1-3 words max) explaining your reason

Return ONLY the JSON object, nothing else."""
            perceived, reasoned, final_action = build_fallback_flow(scenario)
            publish_stage(2, "Perceive complete. Passing extracted scenario facts to Reason.", {
                "turn": 1, "stage": "perceive", "input": task_input,
                "prompt": perceive_prompt,
                "output": perceived, "source": "fallback_simulation"
            })
            time.sleep(1.0)

            # Stage 2: reason from the output of Perceive.
            reason_prompt = f"Previous: {perceived}\nBased on the above, is this correct? Output JSON: action, amount, confidence, rationale"
            publish_stage(3, "Reason complete. Passing the risk estimate and candidate action to Act.", {
                "turn": 2, "stage": "reason", "input": perceived,
                "prompt": reason_prompt,
                "output": reasoned, "source": "fallback_simulation"
            })
            time.sleep(1.0)

            # Stage 3: package the proposed action.
            act_prompt = f"Previous decision: {reasoned}\nFinalize the action. Output JSON: news_label, action, amount, confidence, rationale"
            publish_stage(4, "Act complete. Passing the proposed action to Evaluate.", {
                "turn": 3, "stage": "act", "input": reasoned,
                "prompt": act_prompt,
                "output": final_action, "source": "fallback_simulation"
            })
            time.sleep(1.0)

            # Stage 4: score the action against the scenario answer key.
            score_input = {key: final_action[key] for key in ("news_label", "action", "amount", "confidence")}
            score = score_scenario(score_input, scenario)
            max_score = compute_max_score(scenario)
            evaluation = {
                "score": score,
                "max_score": max_score,
                "normalized": score / max_score if max_score else 0.0,
                "rating_note": "Scorer compared the fallback action with the scenario answer key"
            }
            publish_stage(5, "Evaluate complete. All four fallback stages finished.", {
                "turn": 4, "stage": "observe", "input": score_input,
                "output": evaluation, "source": "scorer"
            })

            with task_lock:
                if run_id != str(task_id):
                    return
                task_result = {
                    "scenario": scenario_file,
                    "scenario_input": {
                        "trigger": scenario.get("trigger"),
                        "financials": scenario.get("financials", {}),
                        "regulations": scenario.get("regulations", {})
                    },
                    "score": score,
                    "max_score": max_score,
                    "normalized": evaluation["normalized"],
                    "final_action": final_action,
                    "trace": list(task_trace),
                    "mode": "fallback_only"
                }
                task_status = "completed"
                task_message = "Fallback run complete. No model/API call was made."
        except Exception as e:
            with task_lock:
                if run_id == str(task_id):
                    task_error = f"Fallback run error: {str(e)}"
                    task_message = task_error
                    task_status = "error"

    threading.Thread(target=run_fallback_async, daemon=True).start()
    return jsonify({"task_id": run_id, "status": "running", "stage": 1, "mode": "fallback_only", "message": task_message})


@app.route("/api/task/<task_id>", methods=["GET"])
def get_task(task_id):
    with task_lock:
        if task_id != str(globals()["task_id"]):
            return jsonify({"error": "Not found"}), 404
        snapshot = {
            "status": task_status,
            "stage": task_stage,
            "trace": list(task_trace),
            "message": task_message,
            "elapsed_seconds": max(0, int(time.monotonic() - task_stage_started_at)),
            "result": dict(task_result),
            "error": task_error,
            "mode": "fallback_only"
        }
    if snapshot["status"] == "error":
        return jsonify(snapshot), 500
    return jsonify(snapshot)


if __name__ == "__main__":
    app.run(port=5000, debug=True)
