# Specialist agents

The dashboard runs the baseline separately from these specialists. No Crisis
Coordinator is implemented, and no specialist's report is fed into the baseline.
All amounts use the synthetic scenario's units; these are simulation rules, not
real banking regulations.

| Module / entry point | Deterministic tools | Output |
| --- | --- | --- |
| `news_verification.run_news_verification` | `retrieve_news`, `cross_check_sources`, `verify_claim` | Source counts and credible / false / unverified verdict |
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

News, risk and compliance accept `llm_runner(prompt)` returning a JSON object,
JSON string, or `(JSON string, model)` tuple. It must contain exactly `summary`
(nonempty string) and `confidence` (finite number from 0 to 1). Interpretation is
separate from the authoritative tool report. Omitting the runner computes the
report without a model. The existing Financial Analyst retains its own
recommendation schema. Treasury is deterministic and does not call an LLM.

Compliance also accepts `proposals=[{"action": "borrow_interbank", "amount": 100}]`.
Without proposals, it checks the same illustrative candidates as Risk Manager.
These candidates are not a selected strategy or a combined decision.

## News evidence fixtures

Existing scenarios contain no independently sourced news records, so their news
verdict remains `unverified`, even if the trigger asserts a claim is confirmed.
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
from article text or supplied by an LLM. Live retrieval is not implemented.
The baseline receives these same records when present. Answer keys remain local.

## Treasury approvals

There is no HTTP approval or execution endpoint. The dashboard always leaves
Treasury awaiting authorization. The following is an explicit host-code simulation
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
the process clears the ledger. A durable ledger and authenticated coordinator
integration are future work.

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
- Until the coordinator exists, the secondary reports are not combined or scored
  as a final decision. The dashboard currently makes five model calls in total:
  baseline, Financial Analyst, News Verification, Risk Manager and Compliance.

Run checks from the repository root:

```powershell
.\frontend\venv\Scripts\python.exe -B -m unittest discover -s frontend -p "test_*.py" -v
```
