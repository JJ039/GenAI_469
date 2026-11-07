# agents/base_agent.py
import json
import os
import shutil
import subprocess
import sys

# Load API keys from .env file into environment BEFORE running the agent
_env_path = None
for _candidate in [
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"),
    os.path.expanduser("~/.hermes/.env"),
    os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"),
    "C:/Users/snake/AppData/Local/hermes/.env",
]:
    if os.path.exists(_candidate):
        _env_path = _candidate
        break

if _env_path and os.path.exists(_env_path):
    with open(_env_path, "r") as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _, _v = _line.partition("=")
                _v = _v.strip().strip('"').strip("'")
                if _k in ("OPENROUTER_API_KEY", "GOOGLE_API_KEY", "OPENROUTER_API_KEY", "GOOGLE_API_KEY"):
                    os.environ[_k.strip()] = _v

from output_schema import validate_decision


def ingest_scenario(file_path):
    """Load a scenario file and return its contents as a string."""
    try:
        with open(file_path, "r") as f:
            return f.read()
    except FileNotFoundError:
        return None


def build_prompt(scenario):
    trigger = scenario.get("trigger", "No trigger provided")
    financials = scenario.get("financials", {}) or {}
    regulations = scenario.get("regulations", {}) or {}

    prompt = f"""
    You are Hermes, a decision-making AI for a bank.
    The following scenario just happened:

    {trigger}

    Here are the bank's current financials:
    - Capital: {financials.get('capital', 'N/A')}
    - Liquidity: {financials.get('liquidity', 'N/A')}
    - Borrowing Limit: {financials.get('borrowing_limit', 'N/A')}
    - Daily Withdrawals: {financials.get('daily_withdrawals', 'N/A')}
    - Forecast Next 7 Days: {financials.get('forecast_next_7d', 'N/A')}

    Here are the relevant regulations:
    - Max Draw Facility: {regulations.get('max_draw_facility', 'N/A')}
    - Report to Regulator: {regulations.get('report_to_regulator', 'N/A')}
    - Max Drawal Rate: {regulations.get('max_drawal_rate_pct', 'N/A')}%

    Please make a decision in JSON format. Your ENTIRE response must be ONLY the JSON object with these exact fields:
    - news_label: "unverified" | "false" | "credible"
    - action: "draw_central_bank_facility" | "borrow_interbank" | "hold"
    - amount: a number
    - confidence: a number between 0.0 and 1.0
    - rationale: a short sentence (1-3 words max) explaining your reason

    Return ONLY the JSON object, nothing else. Do not include any conversational text, explanations, or markdown formatting.
    """

    return prompt


def run_agent(prompt, models=["nvidia/nemotron-3-ultra-550b-a55b:free", "gemini/gemini-2.0-flash"]):
    # Use full path to hermes to avoid PATH resolution issues
    hermes_path = os.environ.get("HERMES_EXECUTABLE") or os.path.expanduser("~/AppData/Local/hermes/hermes-agent/.hermes/bin/hermes.exe")
    if not os.path.exists(hermes_path):
        # Fallback: try to find it on PATH
        hermes_path = shutil.which("hermes")
        if hermes_path is None:
            raise FileNotFoundError("hermes executable not found. Please install Hermes Agent.")
    # hermes CLI uses --model, not --alias
    for model in models:
        cmd = [hermes_path, "chat", "-q", prompt, "--model", model]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=180, errors="replace")
            if res.returncode == 0:
                return res.stdout, model  # returns which model is used
        except subprocess.TimeoutExpired:
            print(f"Model {model} timed out after 180 seconds. Trying next model...")
            continue
        except Exception as e:
            print(f"Model {model} failed with error: {e}. Trying next model...")
            continue
    raise RuntimeError("All configured LLM models failed. Check Hermes credentials, model availability, and connectivity.")


def validate_output(output, prompt):
    """Validate model output with Pydantic. Extract JSON from text and retry if needed."""
    import re
    import json
    max_retries = 3
    attempt = 0

    # Clean up output - handle None and empty strings
    if output is None:
        output = ""
    output = str(output).strip()

    # Initialize json_str with the original output
    json_str = output

    # Try to extract JSON from the output (non-greedy, first balanced object)
    json_match = re.search(r"\{[^{}]*\}", output, re.DOTALL)
    if json_match:
        json_str = json_match.group(0)
        try:
            json_str = json.loads(json_str)
        except json.JSONDecodeError:
            pass  # Keep as string

    while attempt < max_retries:
        # Ensure decision_input is always a dict
        if isinstance(json_str, dict):
            decision_input = json_str
        elif isinstance(output, dict):
            decision_input = output
        else:
            # Try to parse output as dict
            try:
                decision_input = json.loads(output)
            except (json.JSONDecodeError, ValueError):
                decision_input = {}
        valid, errors = validate_decision(decision_input)
        if valid:
            return json_str if isinstance(json_str, dict) else output
        print(f"Validation errors (attempt {attempt + 1}/{max_retries}): {errors}")
        # Extract any JSON-like content (non-greedy)
        json_match = re.search(r"\{[^{}]*\}", output, re.DOTALL)
        if json_match:
            json_str = json_match.group(0)
            try:
                json_str = json.loads(json_str)
            except json.JSONDecodeError:
                pass
        else:
            # Re-prompt with fix instruction
            fix_prompt = prompt + "\n\nIMPORTANT: Your previous output was invalid. Output ONLY valid JSON. No conversational text."
            json_str = run_agent(fix_prompt)
            if json_str is None:
                print("All models failed. Cannot continue.")
                return None
            # Parse the re-prompted output
            json_match = re.search(r"\{[^{}]*\}", json_str, re.DOTALL)
            if json_match:
                try:
                    json_str = json.loads(json_match.group(0))
                except json.JSONDecodeError:
                    pass
            attempt += 1

    print(f"Failed after {max_retries} attempts. Last error: {errors}")
    return None


# Use
if __name__ == "__main__":
    scenario_path = sys.argv[1] if len(sys.argv) > 1 else None
    if scenario_path is None:
        print("Usage: python main_agent.py <scenario_path>")
        sys.exit(1)
    scenario = json.loads(ingest_scenario(scenario_path))
    prompt = build_prompt(scenario)
    model_output = run_agent(prompt)
    model_output = validate_output(model_output, prompt)
    if model_output:
        print(model_output)
    # validate/score your output here
