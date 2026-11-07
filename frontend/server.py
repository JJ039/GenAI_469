from flask import Flask, request, jsonify
from flask_cors import CORS
import json
import math
from pathlib import Path
import sys
import threading
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend" / "agents"))
from main_agent import run_agent, build_prompt
from financial_analyst import run_financial_analyst
from output_schema import HermesBankDecision
from scorer import score_scenario, compute_max_score

# Add future specialist agents here. Each accepts (scenario, llm_runner).
SECONDARY_AGENTS = {"financial_analyst": run_financial_analyst}

app = Flask(__name__)
CORS(app)
SCENARIOS_DIR = ROOT / "backend" / "scenarios" / "scenarios"
task_lock = threading.Lock()
task_result = {}
task_error = None
task_status = "pending"
task_stage = 0
task_trace = []
task_id = 0
task_message = "Waiting to start."
task_stage_started_at = time.monotonic()


def publish_stage(stage, message, trace_entry=None):
    global task_stage, task_trace, task_message, task_stage_started_at
    with task_lock:
        task_stage = stage
        task_message = message
        task_stage_started_at = time.monotonic()
        if trace_entry is not None:
            task_trace = [*task_trace, trace_entry]


def call_llm(prompt):
    response = run_agent(prompt)
    if not response:
        raise RuntimeError("The LLM runner returned no response.")
    raw, model = response
    text = raw.strip()
    if text.startswith("```"):
        text = "\n".join(text.splitlines()[1:-1])
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError) as exc:
        raise ValueError("The LLM returned invalid JSON. Please retry the scenario.") from exc
    if not isinstance(parsed, dict):
        raise ValueError("The LLM response must be a JSON object.")
    return parsed, model


def validate_action(data):
    decision = HermesBankDecision(**data).model_dump()
    if decision["news_label"] not in ("unverified", "false", "credible"):
        raise ValueError("The LLM returned an invalid news label.")
    if decision["action"] not in ("hold", "borrow_interbank", "draw_central_bank_facility"):
        raise ValueError("The LLM returned an invalid action.")
    if not math.isfinite(decision["amount"]) or not math.isfinite(decision["confidence"]):
        raise ValueError("The LLM returned non-finite numbers.")
    if decision["action"] == "hold" and decision["amount"] != 0:
        raise ValueError("A hold decision must have zero amount.")
    return decision


@app.route("/api/scenarios", methods=["GET"])
def list_scenarios():
    files = sorted(p for p in SCENARIOS_DIR.glob("scn_*") if p.is_file())
    return jsonify({"scenarios": [{"id": p.name, "name": p.stem} for p in files]})


@app.route("/api/run", methods=["POST"])
def run_agent_endpoint():
    global task_result, task_error, task_status, task_stage, task_trace, task_id, task_message, task_stage_started_at
    data = request.get_json(silent=True) or {}
    scenario_file = data.get("scenario") if isinstance(data, dict) else None
    allowed = {p.name for p in SCENARIOS_DIR.glob("scn_*") if p.is_file()}
    if not isinstance(scenario_file, str) or scenario_file not in allowed:
        return jsonify({"error": "Choose a valid scenario file."}), 400
    with open(SCENARIOS_DIR / scenario_file, encoding="utf-8") as f:
        scenario = json.load(f)
    # Never send the scoring answer key to the models.
    task_input = {key: scenario.get(key, {}) for key in ("trigger", "financials", "regulations")}
    with task_lock:
        if task_status == "running":
            return jsonify({"error": "An LLM run is already in progress."}), 409
        task_id += 1
        run_id = str(task_id)
        task_result = {}
        task_error = None
        task_stage = 1
        task_trace = []
        task_status = "running"
        task_message = "Main agent is assessing the scenario through Hermes."
        task_stage_started_at = time.monotonic()

    def run_llm_async():
        global task_result, task_error, task_status, task_message
        baseline = {"status": "pending"}
        secondary = {"status": "running", "agents": {}}
        try:
            # The baseline is one standalone main-agent call, with no specialist input.
            prompt = build_prompt(task_input)
            decision, model = call_llm(prompt)
            decision = validate_action(decision)
            score = score_scenario(decision, scenario)
            max_score = compute_max_score(scenario)
            baseline = {
                "status": "completed", "decision": decision, "model": model,
                "score": score, "max_score": max_score,
                "normalized": score / max_score if max_score else 0.0
            }
            publish_stage(2, "Running the independent secondary agent line.", {
                "turn": 1, "stage": "baseline", "input": task_input,
                "prompt": prompt, "output": decision, "source": "main_agent", "model": model,
                "line": "baseline"
            })
        except Exception as exc:
            baseline = {"status": "error", "error": str(exc)}
            publish_stage(2, "Baseline failed. Running the independent secondary agent line.")
        with task_lock:
            task_result = {"baseline": baseline, "secondary": secondary}

        # Specialists see the original scenario only, never the baseline decision.
        for name, agent in SECONDARY_AGENTS.items():
            agent_call = {}

            def specialist_runner(prompt):
                agent_call["prompt"] = prompt
                output, used_model = call_llm(prompt)
                agent_call["model"] = used_model
                return output

            try:
                output = agent(task_input, llm_runner=specialist_runner)
                secondary["agents"][name] = {
                    "status": "completed", "output": output, "model": agent_call["model"]
                }
                publish_stage(2, "Running the secondary agent line.", {
                    "turn": len(task_trace) + 1, "stage": "secondary", "input": task_input,
                    "prompt": agent_call["prompt"], "output": output,
                    "source": name, "model": agent_call["model"], "line": "secondary"
                })
            except Exception as exc:
                secondary["agents"][name] = {"status": "error", "error": str(exc)}

        secondary["status"] = (
            "completed" if all(a["status"] == "completed" for a in secondary["agents"].values())
            else "error"
        )
        secondary["note"] = "Specialist recommendations only. A combined secondary decision is not implemented yet."
        evaluation = {"baseline": {key: baseline[key] for key in ("status", "score", "max_score", "normalized") if key in baseline},
                      "secondary": "Not scored: no combined decision yet."}
        publish_stage(4, "Both lines finished.", {
            "turn": len(task_trace) + 1, "stage": "observe", "output": evaluation, "source": "scorer"
        })
        with task_lock:
            task_result = {
                "scenario": scenario_file, "scenario_input": task_input,
                "baseline": baseline, "secondary": secondary,
                "trace": list(task_trace), "mode": "baseline_and_secondary"
            }
            both_failed = baseline["status"] == "error" and secondary["status"] == "error"
            task_status = "error" if both_failed else "completed"
            task_error = ("Both lines failed. Baseline: " + baseline.get("error", "") +
                          "; Secondary: " + "; ".join(a.get("error", "") for a in secondary["agents"].values())) if both_failed else None
            task_message = "Both lines finished. Check each line for its result or error."

    threading.Thread(target=run_llm_async, daemon=True).start()
    return jsonify({"task_id": run_id, "status": "running", "stage": 1, "mode": "baseline_and_secondary", "message": "LLM agents started."})


@app.route("/api/task/<run_id>", methods=["GET"])
def get_task(run_id):
    with task_lock:
        if run_id != str(task_id):
            return jsonify({"error": "Not found"}), 404
        snapshot = {
            "status": task_status, "stage": task_stage, "trace": list(task_trace),
            "message": task_message, "elapsed_seconds": max(0, int(time.monotonic() - task_stage_started_at)),
            "result": dict(task_result), "error": task_error, "mode": "baseline_and_secondary"
        }
    return jsonify(snapshot)


if __name__ == "__main__":
    app.run(port=5000, debug=True)
