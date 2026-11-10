# Specialist agents

The dashboard runs the baseline separately from these specialists. The combined decision stage is owned by a teammate and is not implemented here. No specialist report is fed into the baseline.
All amounts use the synthetic scenario's units; these are simulation rules, not
real banking regulations.

| Module / entry point | Deterministic tools | Output |
| --- | --- | --- |
| `news_verification.run_news_verification` | `retrieve_news`, `cross_check_sources`, `verify_claim` | Source counts, injection flags, and credible / false / unverified verdict |
| `financial_analyst.run_financial_analyst` | Existing financial tools | Metrics and bounded funding recommendation |
| `risk_manager.run_risk_manager` | `calculate_risk_score`, `simulate_action_outcome` | Current risk proxy and outcomes for three candidate actions |
| `compliance_officer.run_compliance_officer` | `retrieve_regulations`, `check_compliance` | Funding limit checks, violations, reporting requirement |
| `treasury_operations.run_treasury_operations` | Approval ledger and simulated treasury tools | Awaiting authorization, or an approved simulated receipt |

## Running specialists

Run Python from the repository root so `backend` and `tools` are importable:

```python
import json
from backend.agents.risk_manager import run_risk_manager

with open("backend/scenarios/scenarios/scn_002_true_rumor_unhealthy.json") as f:
    scenario = json.load(f)

print(json.dumps(run_risk_manager(scenario), indent=2))
```

Risk and compliance accept `llm_runner(prompt)` returning a JSON object,
JSON string, or `(JSON string, model)` tuple. It must contain exactly `summary`
(nonempty string) and `confidence` (finite number from 0 to 1). Interpretation is
separate from the authoritative tool report. Omitting the runner computes the
report without a model. The existing Financial Analyst retains its own
recommendation schema. News and Treasury preparation use the bounded tool protocol below.
Treasury execution remains deterministic and does not call an LLM.

## Topic 7 agentic upgrades

News Verification and Treasury preparation now use a shared perceive/action/observation
loop in `agent_loop.py`. Each has a role-specific allowlist, six model-turn and four
tool-call defaults, validated JSON envelopes, a host-maintained observation scratchpad,
and a complete `react_trace`. Invalid calls and final citations return feedback within
the same budget. Final summaries cite successful observation IDs; exhausted loops
return no accepted interpretation. These checks validate citations exist, not the
semantic truth of every sentence in a summary.

The protocol is application-level JSON tool calling, not provider-native function
calling. It works with the existing text client without installing Groq, LangGraph
or MCP. No notebook code or notebook instructions are executed.

- News can retrieve all source documents, inspect an exact source ID, cross-check
  independent groups, and request the authoritative verdict. It must cite retrieval
  and verification observations before completing. The host verdict and source
  metadata remain authoritative; this is not independent raw-document fact-checking
  or live retrieval. Its report remains available when interpretation needs review.
- Financial Analyst retains its numeric grounding and action bounds. Failed final
  validation now feeds back into the next turn so the model can correct its answer.
  A host scratchpad exposes successful observation IDs and the last validation.
- Treasury can inspect the host candidate, read simulation rules and prepare an
  execution plan. The dashboard supplies the Financial Analyst candidate for
  preparation only; it is not a selected combined strategy. The plan records
  compliance, missing requirements and reporting steps. No approval or execution
  operation is available to the model. Existing host-approved ledger execution
  retains exact binding, remaining-limit checks and idempotency.

News and Treasury outputs include `analysis_metrics` for steps, requested/valid/invalid
calls, call success rate, task completion and exhaustion. Treasury continues to
return `awaiting_authorization`, even if preparation completes. The deterministic
no-runner path remains available for all three roles.

Compliance also accepts `proposals=[{"action": "borrow_interbank", "amount": 100}]`.
Without proposals, it checks the same illustrative candidates as Risk Manager.
These candidates are not a selected strategy or a combined decision.

## News evidence fixtures

Version-2 scenarios include controlled evidence fixtures. Claims without corroboration remain `unverified`, even if a trigger asserts confirmation.
For controlled experiments, the scenario designer can add:

```json
{
  "news_sources": [
    {"source_id": "source_a", "independence_group": "group_a", "trusted": true,
     "verdict": "supports", "content": "Synthetic source record A"},
    {"source_id": "source_b", "independence_group": "group_b", "trusted": true,
     "verdict": "supports", "content": "Synthetic source record B"}
  ]
}
```

Two independent trusted groups supporting the claim produce `credible`; two
refuting it produce `false`. Any conflicting trusted evidence produces
`unverified`. Repeated sources from one group do not count as corroboration.
Trust, provenance and verdict are controlled fixture metadata, not values inferred
from article text or supplied by an LLM. Live retrieval is not implemented. The
report also marks all news as untrusted content and detects a small set of
instruction-like phrases in the trigger or source content. These phrases are
reported for injection analysis and are never used as evidence or instructions.
Source IDs must be unique, source groups must be nonempty, and `trusted` must be
a boolean so malformed fixtures fail before evaluation.
The baseline receives these same records when present. Answer keys remain local.

## Treasury approvals

There is no public HTTP approval endpoint. The dashboard never issues approval or executes a combined strategy. Treasury waits for an explicit host-issued approval. Its standalone simulation tools remain available for future integration. The following is an explicit host-code simulation
example, not a model-callable workflow:

```python
from tools.treasury_tools import TreasurySimulation
from backend.agents.treasury_operations import run_treasury_operations

book = TreasurySimulation(authorized_approvers=("human_reviewer",))
proposal = {"action": "borrow_interbank", "amount": 100}
# Host authenticates the reviewer and obtains their approval before this call.
approval_id = book.approve(scenario, proposal, approved_by="human_reviewer")
result = run_treasury_operations(
    scenario, book=book, proposal=proposal, approval_id=approval_id
)
```

`approved_by` is an audit identity, not an authentication mechanism. Trusted host
code must authenticate approvals and must never expose `approve` to the model or
accept identities from untrusted requests. The process-local ledger binds an
approval to exact scenario inputs, action and amount. Execution rechecks remaining
limits, tracks cumulative funding per scenario, and returns the same receipt on
retries. No real funds move; regulator reports are flagged but never sent. Restarting
the process clears the ledger. A durable approval ledger for resumable simulations is future work.

## Limits of the current experiment

- Risk score is the percentage of projected seven-day cash outflow left unfunded,
  not a calibrated default probability. Simulations assume immediate successful
  funding and exclude interest, market impact and contagion.
- Compliance enforces interbank borrowing limits and facility draw limits, finite
  amounts, and known actions. Missing facility limits block facility draws. The
  regulator reporting requirement is surfaced. Other fields such as
  `max_drawal_rate_pct` are explicitly reported as unmodelled because their
  operational meaning has not been defined.
- An LLM summary cannot replace deterministic verdicts or grant execution approval.
  Summaries can still be wrong and should be evaluated separately.
- The secondary line returns reports only, with no combined decision or score. News, Financial Analyst and Treasury preparation each use up to six model turns by default. Risk and Compliance each use one call. Treasury execution uses no model call. Complete-run costs depend on the trajectories; the current mock fixture takes ten calls and is not evidence of LLM performance.

Run checks from the repository root:

```powershell
.\frontend\venv\Scripts\python.exe -B -m unittest discover -s frontend -p "test_*.py" -v
```

See [Financial Analyst ReAct and numeric grounding](../../docs/FINANCIAL_ANALYST.md) for its revised final-response protocol, budgets and diagnostic fields.
