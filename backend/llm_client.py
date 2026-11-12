"""One model/temperature for both systems; no silent provider fallback.

OpenRouter transport makes plain inference requests with no tools. Optional Hermes
transport is isolated from project rules and disables its toolsets. Missing usage
is recorded as null, never estimated as measured tokens.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import requests

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MODEL = "nvidia/nemotron-3-ultra-550b-a55b:free"


def load_credentials():
    native = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "hermes"
    candidates = [ROOT / "backend/.env", Path.home() / ".hermes/.env", native / ".env"]
    for path in candidates:
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            key, sep, value = line.strip().partition("=")
            if sep and key in {"OPENROUTER_API_KEY", "GROQ_API_KEY", "GOOGLE_API_KEY", "LLM_MODEL", "LLM_TRANSPORT", "LLM_PROVIDER", "HERMES_EXECUTABLE", "LLM_MAX_TOKENS", "LLM_REASONING_EFFORT"}:
                cleaned = value.strip().strip('"').strip("'")
                if cleaned:
                    os.environ.setdefault(key, cleaned)


class LLMClient:
    def __init__(self, model=None, temperature=0.1, transport=None, timeout=180, max_tokens=None, reasoning_effort=None):
        load_credentials()
        self.temperature = temperature
        self.transport = transport or os.environ.get("LLM_TRANSPORT", "openrouter")
        default_model = "qwen3:1.7b" if self.transport == "ollama" else DEFAULT_MODEL
        self.model = model or os.environ.get("LLM_MODEL", default_model)
        self.timeout = timeout
        self.max_tokens = max_tokens or int(os.environ.get('LLM_MAX_TOKENS', '4096'))
        self.reasoning_effort = reasoning_effort or os.environ.get('LLM_REASONING_EFFORT', 'low')
        if self.max_tokens < 256:
            raise ValueError('max_tokens must be at least 256')
        if self.reasoning_effort not in ('none','minimal','low','medium','high'):
            raise ValueError('Unsupported reasoning effort')
        if self.transport not in ("openrouter", "groq", "ollama", "hermes"):
            raise ValueError("transport must be openrouter, groq, ollama or hermes")
        if not 0 <= temperature <= 2:
            raise ValueError("temperature must be between 0 and 2")

    def complete(self, prompt):
        start = time.monotonic()
        if self.transport == "openrouter":
            key = os.environ.get("OPENROUTER_API_KEY")
            if not key:
                raise RuntimeError("Missing OPENROUTER_API_KEY. Configure backend/.env or your Hermes credentials.")
            try:
                response = requests.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={"Authorization": "Bearer " + key},
                    json={"model": self.model, "messages": [{"role": "user", "content": prompt}],
                          "temperature": self.temperature, "max_tokens": self.max_tokens,
                          "reasoning": {"effort": self.reasoning_effort, "exclude": True}}, timeout=self.timeout)
            except requests.RequestException as exc:
                raise RuntimeError("OpenRouter connection failed: " + type(exc).__name__) from exc
            if response.status_code != 200:
                reasons = {401: "Invalid or missing API key", 402: "Insufficient credits", 404: "Model unavailable",
                           429: "Rate limit reached", 503: "No available provider"}
                raise RuntimeError(f"OpenRouter HTTP {response.status_code}: {reasons.get(response.status_code, 'Request failed')}. Model: {self.model}")
            data = response.json()
            if data.get("error") or not data.get("choices"):
                raise RuntimeError("OpenRouter returned no completion; check model availability")
            text = data["choices"][0]["message"].get("content")
            if text is None:
                text = ""
            if not isinstance(text, str):
                raise RuntimeError("The model returned non-text content")
            usage = data.get("usage") or {}
            result = {"text": text, "model": data.get("model", self.model),
                      "input_tokens": usage.get("prompt_tokens"), "output_tokens": usage.get("completion_tokens"),
                      "cost_usd": usage.get("cost"), "temperature": self.temperature,
                      "usage_source": "provider", "provider_calls": 1,
                      "finish_reason": data['choices'][0].get('finish_reason'),
                      "generation_id": data.get("id"), "provider_route": data.get("provider"),
                      "reasoning_tokens": (usage.get('completion_tokens_details') or {}).get('reasoning_tokens')}
        elif self.transport == "groq":
            key = os.environ.get("GROQ_API_KEY")
            if not key:
                raise RuntimeError("Missing GROQ_API_KEY. Configure backend/.env.")
            payload = {"model": self.model, "messages": [{"role": "user", "content": prompt}],
                       "temperature": self.temperature, "max_completion_tokens": self.max_tokens}
            if self.model in ("openai/gpt-oss-120b", "openai/gpt-oss-20b"):
                if self.reasoning_effort not in ("low", "medium", "high"):
                    raise ValueError("Groq GPT-OSS reasoning effort must be low, medium or high")
                payload.update(reasoning_effort=self.reasoning_effort, include_reasoning=False)
            try:
                response = requests.post("https://api.groq.com/openai/v1/chat/completions",
                                         headers={"Authorization": "Bearer " + key},
                                         json=payload, timeout=self.timeout)
            except requests.RequestException as exc:
                raise RuntimeError("Groq connection failed: " + type(exc).__name__) from exc
            if response.status_code != 200:
                reasons = {401: "Invalid API key", 404: "Model unavailable", 429: "Rate limit reached"}
                retry = response.headers.get('retry-after')
                suffix = f" Retry after {retry} seconds." if isinstance(retry, str) and retry else ""
                raise RuntimeError(f"Groq HTTP {response.status_code}: {reasons.get(response.status_code, 'Request failed')}. Model: {self.model}." + suffix)
            data = response.json()
            if data.get('error') or not data.get('choices'):
                raise RuntimeError("Groq returned no completion")
            text = data['choices'][0]['message'].get('content') or ''
            if not isinstance(text, str):
                raise RuntimeError("Groq returned non-text content")
            usage = data.get('usage') or {}
            result = {'text': text, 'model': data.get('model', self.model),
                      'input_tokens': usage.get('prompt_tokens'), 'output_tokens': usage.get('completion_tokens'),
                      'cost_usd': None, 'temperature': self.temperature, 'usage_source': 'provider',
                      'provider_calls': 1, 'finish_reason': data['choices'][0].get('finish_reason'),
                      'generation_id': data.get('id')}
        elif self.transport == "ollama":
            try:
                response = requests.post(
                    "http://127.0.0.1:11434/api/chat",
                    json={"model": self.model,
                          "messages": [{"role": "user", "content": prompt}],
                          "stream": False, "format": "json", "think": False,
                          "options": {"temperature": self.temperature,
                                      "num_predict": self.max_tokens, "num_ctx": 16384}},
                    timeout=self.timeout)
            except requests.RequestException as exc:
                raise RuntimeError("Local Ollama request failed. Check that Ollama is running. "
                                   + type(exc).__name__) from exc
            if response.status_code != 200:
                hint = f" Run ollama pull {self.model} first." if response.status_code == 404 else " Check Ollama memory usage and server logs."
                raise RuntimeError(f"Ollama HTTP {response.status_code}. Model: {self.model}." + hint)
            data = response.json()
            text = (data.get("message") or {}).get("content")
            if not isinstance(text, str):
                raise RuntimeError("Ollama returned no text completion")
            result = {"text": text, "model": data.get("model", self.model),
                      "input_tokens": data.get("prompt_eval_count"),
                      "output_tokens": data.get("eval_count"), "cost_usd": 0.0,
                      "temperature": self.temperature, "usage_source": "local_ollama",
                      "provider_calls": 1, "finish_reason": data.get("done_reason"),
                      "requested_num_ctx": 16384, "thinking_enabled": False}
        else:
            native = Path(os.environ.get("LOCALAPPDATA", "")) / "hermes/bin/hermes.exe"
            executable = os.environ.get("HERMES_EXECUTABLE") or shutil.which("hermes") or (str(native) if native.is_file() else None)
            if not executable:
                raise FileNotFoundError("Hermes executable not found. Set HERMES_EXECUTABLE or use OpenRouter transport.")
            cmd = [executable, "chat", "-Q", "--oneshot", "--format", "stream-json",
                   "--ignore-rules", "--toolsets", "", "--model", self.model,
                   "--provider", os.environ.get("LLM_PROVIDER", "openrouter"), "--query-file", "-"]
            proc = subprocess.run(cmd, input=prompt, text=True, encoding="utf-8", errors="replace",
                                  capture_output=True, timeout=self.timeout)
            events = []
            for line in proc.stdout.splitlines():
                try:
                    event = json.loads(line)
                    if isinstance(event, dict):
                        events.append(event)
                except ValueError:
                    continue
            result_event = next((e for e in reversed(events) if e.get("type") == "result"), None)
            if proc.returncode or not result_event or result_event.get("exit_code"):
                details = (proc.stderr + proc.stdout).lower()
                reason = ("Missing provider API key" if "no api key" in details else
                          "Model unavailable" if "404" in details else "Hermes request failed; test the configured provider/model directly")
                raise RuntimeError(reason)
            if any(e.get("type") == "tool_use" for e in events):
                raise RuntimeError("Hermes unexpectedly attempted a tool call; evaluation aborted")
            tokens = result_event.get("tokens") or {}
            result = {"text": result_event.get("text", ""), "model": self.model,
                      "input_tokens": tokens.get("input"), "output_tokens": tokens.get("output"),
                      "cost_usd": None, "temperature": None, "provider_calls": None,
                      "usage_source": "hermes; temperature controlled by installed Hermes config"}
        result["requested_max_tokens"] = self.max_tokens
        result["requested_reasoning_effort"] = self.reasoning_effort
        result["elapsed_seconds"] = time.monotonic() - start
        result["transport"] = self.transport
        return result
