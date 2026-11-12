"""Dashboard API backed by the same orchestration and evaluator as the CLI."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import threading
import time
from flask import Flask, request, jsonify
from flask_cors import CORS

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from backend.llm_client import LLMClient
from backend.systems import run_system
from backend.agents.main_agent import scenario_inputs
from backend.scenarios.validation import load_scenarios

app = Flask(__name__)
CORS(app)
SCENARIOS_DIR = ROOT / 'backend/scenarios/scenarios'
task_lock = threading.Lock()
task_status = 'pending'
task_id = 0
task_stage = 0
task_trace = []
task_result = {}
task_error = None
task_message = 'Waiting to start.'
task_stage_started_at = time.monotonic()


def make_client():
    return LLMClient()


@app.get('/api/scenarios')
def list_scenarios():
    try:
        scenarios = load_scenarios(SCENARIOS_DIR)
    except (ValueError, KeyError, TypeError) as exc:
        return jsonify(error='Scenario validation failed: ' + str(exc)), 500
    return jsonify(scenarios=[{'id':p.name,'name':s.get('name',p.stem)} for p,s in scenarios])


@app.post('/api/run')
def start_run():
    global task_status, task_id, task_stage, task_trace, task_result, task_error, task_message, task_stage_started_at
    data = request.get_json(silent=True)
    scenario_file = data.get('scenario') if isinstance(data,dict) else None
    allowed = {p.name:p for p in SCENARIOS_DIR.glob('scn_*.json')}
    if not isinstance(scenario_file,str) or scenario_file not in allowed:
        return jsonify(error='Choose a valid scenario file.'), 400
    scenario = json.loads(allowed[scenario_file].read_text(encoding='utf-8'))
    with task_lock:
        if task_status == 'running':
            return jsonify(error='An evaluation is already running.'), 409
        task_id += 1
        run_id = str(task_id)
        task_status, task_stage = 'running', 1
        task_trace, task_result, task_error = [], {}, None
        task_message = 'Running independent baseline.'
        task_stage_started_at = time.monotonic()

    def worker():
        global task_status, task_stage, task_trace, task_result, task_error, task_message, task_stage_started_at
        def update(entry):
            global task_message, task_stage_started_at
            with task_lock:
                if entry.get('state') != 'running':
                    task_trace.append(entry)
                task_message = entry['source'].replace('_',' ') + (' is calling the model.' if entry.get('state') == 'running' else ' finished.')
                task_stage_started_at = time.monotonic()
        try:
            client = make_client()
            baseline = run_system(scenario,'baseline',client,update)
            with task_lock:
                task_result = {'baseline':baseline}
                task_stage = 2
                task_message = 'Collecting specialist reports. Treasury awaits explicit approval.'
                task_stage_started_at = time.monotonic()
            secondary = run_system(scenario,'multi_agent',client,update)
            result = {'scenario':scenario_file,'scenario_input':scenario_inputs(scenario),
                      'baseline':baseline,'secondary':secondary,'mode':'baseline_and_multi_agent'}
            # Persist every dashboard result, including model errors and unsafe proposals.
            directory = ROOT/'results/dashboard'
            directory.mkdir(parents=True,exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
            (directory/(stamp+'.json')).write_text(json.dumps(result,indent=2,allow_nan=False),encoding='utf-8')
            with task_lock:
                task_result = result
                task_stage = 3
                task_trace.append({'stage':'observe','source':'shared_evaluator','output':{
                    'baseline':baseline['metrics'],'multi_agent':secondary['metrics']}})
                both_failed = baseline['status']=='error' and secondary['status']=='error'
                was_cancelled = task_status == 'cancelling'
                task_status = 'cancelled' if was_cancelled else 'error' if both_failed else 'completed'
                task_error = ('Both lines failed. Baseline: ' + baseline.get('error','') + '; Multi-agent: ' + secondary.get('error','')) if both_failed else None
                task_message = 'Run cancelled.' if was_cancelled else 'Evaluation finished. Execution is simulated only.'
        except Exception as exc:
            with task_lock:
                task_status='error'
                task_error=str(exc)
                task_message='Evaluation failed.'
    threading.Thread(target=worker,daemon=True).start()
    return jsonify(task_id=run_id,status='running',stage=1,message='Evaluation started.')


@app.get('/api/task/<run_id>')
def get_task(run_id):
    with task_lock:
        if run_id != str(task_id):
            return jsonify(error='Not found'),404
        return jsonify(status=task_status,stage=task_stage,trace=deepcopy(task_trace),
                       result=deepcopy(task_result),error=task_error,message=task_message,
                       elapsed_seconds=max(0,int(time.monotonic()-task_stage_started_at)))

@app.post('/api/cancel')
def cancel_run():
    """Cancel the current evaluation run."""
    global task_status, task_message, task_stage_started_at
    data = request.get_json(silent=True)
    requested_task_id = data.get('task_id') if isinstance(data, dict) else None
    with task_lock:
        if task_status != 'running':
            return jsonify(error='There is no active run to cancel.'), 409
        if requested_task_id is not None and str(requested_task_id) != str(task_id):
            return jsonify(error='This run has already changed. Refresh the page and try again.'), 409
        task_status = 'cancelling'
        task_message = 'Cancellation requested. Waiting for the current model call to finish.'
        task_stage_started_at = time.monotonic()
    from backend.agents.main_agent import set_cancel
    set_cancel()
    return jsonify(status='cancelling', message=task_message), 202


if __name__ == '__main__':
    app.run(port=5000,debug=False)
