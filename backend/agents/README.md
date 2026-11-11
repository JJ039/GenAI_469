# Specialist agents

The dashboard runs the baseline separately from these specialists. The combined decision stage is owned by a teammate and is not implemented here. No specialist report is fed into the baseline.
All amounts use the synthetic scenario's units; these are simulation rules, not
real banking regulations.

| Module / entry point | Deterministic tools | Output |
| --- | --- | --- |
| `news_verification.run_news_verification` | `retrieve_news`, `cross_check_sources`, `verify_claim` | Source counts, injection flags, and credible / false / unverified verdict |
| `financial_analyst.run_financial_analyst` | Existing financial tools | Metrics and bounded funding recommendation |
| `risk_manager.run_risk_manager` | `calculate_risk_score`, `simulate_action_outcome` | Current risk proxy and outcomes for three candidate actions |
| `compliance_officer.run_compliance_officer` | Synthetic checks plus bounded Qwen/Qdrant + local BM25 retrieval | Separate simulation checks and cited regulatory finding for each proposal |
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

News and Risk accept `llm_runner(prompt)` returning a JSON object, JSON string,
or `(JSON string, model)` tuple with `summary` and `confidence`. Interpretation
is separate from their authoritative tool reports. Omitting the runner computes
those reports without a model. Compliance uses its bounded protocol below. The
existing Financial Analyst retains its own recommendation schema. Treasury is
deterministic and does not call an LLM.

### Compliance coordinator interface

The host/coordinator passes proposed actions and scenario facts to the Python entry
point; Compliance reviews those inputs and does not recalculate Risk Manager's
evaluation. The existing `systems.py` wiring is intentionally not changed by this
interface handoff.

```python
from backend.agents.compliance_officer import run_compliance_officer

result = run_compliance_officer(
    scenario,
    llm_runner=llm_runner,
    proposals=[
        {"action": "borrow_interbank", "amount": 100},
        {"action": "draw_central_bank_facility", "amount": 25},
    ],
    scenario_facts={
        "financials": scenario["financials"],
        "regulations": scenario.get("regulations", {}),
    },
)
```

Input contract:

- `scenario` is the existing scenario object used by deterministic simulation
  checks. Keep `answer_key` and news/trigger content out of `scenario_facts`.
- `proposals` is a list of objects with `action` and nonnegative numeric `amount`;
  multiple proposals produce one result each, in input order. Omitting it retains
  the illustrative candidate behavior for backwards compatibility.
- `scenario_facts` is an optional coordinator-selected object containing only
  facts relevant to compliance. If omitted, the agent passes only `id`,
  `financials`, and `regulations` to its regulatory-review model.
- `llm_runner(prompt)` returns a JSON object (or JSON string / tuple whose first
  item is either), as with the other specialist agents.

For each proposal, the model protocol returns either
`{"type":"retrieve","query":"..."}` or a final object with `finding`
(`compliant`, `non_compliant`, or `undetermined`), `rationale`, cited
`evidence_id` values, and `missing_facts`. Python enforces at most three model
turns and three hybrid retrieval calls per proposal, with at most five passages
per retrieval. Each retrieval combines Qwen/Qdrant dense results with BM25 over
the local PDFs using reciprocal-rank fusion. Citations preserve source, source
type, authority class, URL, effective date and PDF page range. Passage authority
is grouped as binding rule, guidance, enforcement example, or unclassified;
enforcement examples are not treated as binding rules.

An `undetermined` result means the evidence or scenario facts did not support a
reliable regulatory conclusion within the fixed budget. The coordinator should
surface it for review and must not treat it as compliant or as authorization.
`report.synthetic_checks` retains the existing deterministic scenario-limit
checks; `report.regulatory_findings` contains real-source review results. Both
are reports only and `authorization_granted` remains false.

To run five standalone live RAG cases (two compliant, two non-compliant and one
undetermined) and print all retrieved passages, citations, findings and budgets:

```powershell
.\frontend\venv\Scripts\python.exe -m backend.agents.test_compliance_rag
```

The cases are narrowly grounded in MAS Notice 649 Part I MLA paragraphs 13 and
15. Each run calls Compliance directly and does not invoke the coordinator.

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
- Compliance retains deterministic synthetic checks for interbank borrowing and
  facility draw limits, finite amounts, and known actions. It separately returns
  bounded, cited regulatory findings; an undetermined result requires review.
- An LLM summary cannot replace deterministic verdicts or grant execution approval.
  Summaries can still be wrong and should be evaluated separately.
- The secondary line returns reports only, with no combined decision or score. Financial Analyst uses up to six model turns. Compliance uses up to three model turns per proposed action, so complete-run call counts vary with the number of proposals. News and Risk use one call each, plus the standalone baseline call. Treasury makes no model call and waits for authorization.

Run checks from the repository root:

```powershell
.\frontend\venv\Scripts\python.exe -B -m unittest discover -s frontend -p "test_*.py" -v
```

See [Financial Analyst ReAct and numeric grounding](../../docs/FINANCIAL_ANALYST.md) for its revised final-response protocol, budgets and diagnostic fields.
