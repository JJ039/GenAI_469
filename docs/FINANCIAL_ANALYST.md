# Financial Analyst: dynamic tool use and numeric hallucination checks

These enhancements are limited to the Financial Analyst and its report consumers.
The baseline remains a single plain LLM inference call. No combined decision agent
or automatic approval has been added.

## 1. Bounded ReAct-style tool calling

Previously the host calculated the entire financial report and asked the model
for one interpretation. The analyst now chooses actions at runtime:

1. The model chooses an allowlisted tool and arguments.
2. The host validates the action and executes the real deterministic function
   against a copy of the trusted scenario inputs.
3. The host returns an observation with a unique id.
4. The model can request another tool or produce its final recommendation.

This is an application-level JSON action/observation protocol. It does not depend
on vendor-native function calling, and does not request or expose private chain
of thought. Optional `purpose` is a short task description only. Existing
`llm_runner(prompt)` callbacks and both configured inference transports work.
Each model turn is a real inference call and appears in usage telemetry.

Default limits are six model turns and four tool requests, configurable through
`run_financial_analyst(..., max_steps=6, max_tool_calls=4)`. Invalid requests count
toward the budgets and return error observations. Provider/network errors fail
immediately rather than causing repeated quota-consuming retries.

Tools: `get_bank_financials`, `calculate_liquidity_ratio`, `forecast_cash_outflow`,
`calculate_funding_gap`, `calculate_cash_runway`, `calculate_borrowing_capacity`,
and `build_financial_report`. Only the forecast tool accepts arguments: integer
`days` from 1 to 30. All other argument objects must be empty. The model cannot
supply replacement financial figures, code, scenario data, approval or Treasury
commands. `build_financial_report` must be observed before finalizing.

Example tool action:

```json
{"type":"tool_call","tool":"build_financial_report","arguments":{}}
```

The host returns `obs_1` with the actual result. An example final answer for a
scenario with zero funding gap:

```json
{
  "type": "final",
  "recommendation": {
    "recommendation": "hold",
    "amount": 0,
    "confidence": 0.8,
    "rationale": "Funding gap is zero. Hold while monitoring withdrawals."
  },
  "claims": [
    {"metric":"funding_gap","value":0,"unit":"amount","observation_id":"obs_1"}
  ]
}
```

Tool order is not hard-coded. The model may start with a ratio, forecast or bank
financials, and select the evidence it needs. A report computed by the host after
budget exhaustion is an audit-only fallback; it is never represented as evidence
that the model observed, and no recommendation is accepted in that case.

## 2. Financial hallucination detection

`tools/financial_tools.py` checks the final response against successful,
host-generated tool observations, not the answer key or an LLM judge.

- Every structured claim names a numeric metric, its value, unit and observation id.
- Wrong values, forged references, unobserved metrics and incompatible units are flagged.
- Amount scales (thousand/million/billion), ratios/percentages and days normalize
  before comparison. Numeric tolerances are 0.5% relative and 0.0001 absolute.
- Numeric assertions in the rationale are checked using metric aliases and local
  clauses, so a correct capital figure attributed to liquidity can be detected.
- Day-based expressions such as `7-day horizon`, `7-day period`, `7-day window`,
  `7-day time frame`, and `over 7 days` are treated as forecast-horizon metadata,
  not monetary claims. This prevents a time number from being associated with a
  nearby metric such as `funding_gap`.
- Supported comparisons such as a runway under one day are checked as inequalities.
- Calling the liquidity/capital proxy regulatory LCR is flagged; an explicit
  statement that it is not regulatory LCR is allowed.
- Existing action-specific amount, finite-number and confidence bounds still apply.

A failed check returns `status="needs_review"`, `recommendation=null`, the original
candidate, and flags. The rejected candidate remains available for audit, but Risk
Manager receives only trusted metrics, the validated recommendation (if any),
status and a safe review reason. Compliance sees no proposal when the financial
recommendation is withheld. No financial action is executed.

This detector is deliberately limited: citation checks and numeric comparisons
are deterministic; prose-to-metric association is heuristic. It does not establish
all causal, semantic or regulatory claims, and may flag legitimate rounding or
unusual phrasing. Unsupported citations are grounding failures, not automatically
proof that the underlying figure is false. Horizon handling is covered by a
regression test based on a real model rationale. Human review is still necessary.

## Evidence of the enhancement

Analyst output includes `react_trace`, `hallucination_check`, `financial_claims` and
`analysis_metrics`. The dashboard Agent activity view displays verification status,
step/tool counts, grounded claim rate, flags, and expandable action/observation
records. Complete raw records remain in `runs.jsonl`.

Batch CSV now includes `financial_*` columns for:

- ReAct steps and requested / valid / invalid tool calls.
- Loop completion and recommendation acceptance / blocking.
- Checks performed, total validation flags and suspected numeric hallucination flags.
- Grounded claim rate and number of claims checked.

`hallucination_flags` counts suspected numeric/regulatory errors;
`validation_flags` also includes missing citations and schema/bound errors.
These are model-output diagnostics, not an independently measured precision/recall.
Blocked recommendations count as unsuccessful financial recommendations rather
than disappearing from the accuracy denominator. An exhausted loop has no final
claim check and a null grounded-claim rate.

Run offline regression checks without provider usage:

```powershell
.\frontend\venv\Scripts\python.exe -B -m unittest discover -s frontend -p "test_*.py" -v
```

Run the planted-error benchmark:

```powershell
.\frontend\venv\Scripts\python.exe backend/scripts/check_financial_guardrails.py
```

The benchmark generates valid amount/percentage claims, incorrect cited values,
incorrect prose figures, fabricated citations and unsupported LCR assertions from
the authored scenarios. It reports true/false positives/negatives, precision,
recall and false-positive rate, with every case saved to JSON. Missing required
financial data are explicitly skipped. These results validate the detector on
controlled planted errors; they are not live-model hallucination rates or proof
of generalization. Use separately human-labelled live outputs to evaluate that.

## Reflection and future work

The implementation makes evidence acquisition inspectable and prevents flagged
financial recommendations from propagating downstream. Deterministic tools remain
responsible for arithmetic; the model selects tools and interprets observations.

The trade-off is extra inference latency and quota use: the financial stage now
uses up to six calls rather than one. Short budgets may cause deferral, and local
numeric text matching can miss implicit claims or produce false alarms. Measure
these costs alongside recommendation quality and blocked-error counts.

A concrete next step is to label a held-out set of real analyst responses with
wrong-metric, wrong-unit and unsupported-citation errors, then compare detection
precision/recall and false blocks with the current planted-error benchmark.
