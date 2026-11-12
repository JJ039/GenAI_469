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

Risk accepts `llm_runner(prompt)` returning a JSON object,
JSON string, or `(JSON string, model)` tuple. It must contain exactly `summary`
(nonempty string) and `confidence` (finite number from 0 to 1). Interpretation is
separate from the authoritative tool report. Omitting the runner computes the
report without a model. The existing Financial Analyst retains its own
recommendation schema. News and Treasury preparation use the bounded tool protocol below.
Compliance uses its own bounded regulatory-review protocol described under
"Compliance coordinator interface".
Treasury execution remains deterministic and does not call an LLM.

## Topic 7 agentic upgrades

News Verification and Treasury preparation each own a perceive/action/observation
loop in their respective agent modules. Each has a role-specific allowlist, six model-turn and four
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

### Expanded tool choices for the existing scenarios

Each agent's tool implementations, catalog and argument-validation dispatcher now
live together under `tools/`:

- `tools/news_tools.py`: seven news tools, `TOOL_CATALOG`, `execute_news_tool`.
- `tools/financial_tools.py`: nine financial tools, `TOOL_CATALOG`, `execute_financial_tool`.
- `tools/treasury_tools.py`: six preparation tools, `TOOL_CATALOG`,
  `execute_treasury_tool`, plus the host-only approval ledger/execution helpers.

Agent modules retain prompts, loop orchestration and output validation. Common
compliance calculations remain in `tools/compliance_tools.py`. Numeric grounding
(`check_financial_hallucinations`) lives in `tools/financial_tools.py` and is called
automatically by the host after a candidate final response. It is not an optional
model-selectable tool and does not consume the four-call model tool budget.
All callers import diagnostics directly from their agent toolkit modules;
the obsolete `scenario_diagnostics.py` compatibility file has been removed.

There are now 22 model-selectable tools across these three roles: News 7,
Financial Analyst 9, Treasury 6. The defaults remain six turns and four requested
tool calls per agent. A toolkit is a menu, not a sequence to exhaust. Existing
required evidence tools still apply; diagnostics are optional choices. No scenario
inputs, difficulty, financial targets or answer keys were changed.

| Role | Added tools | Use with existing cases |
| --- | --- | --- |
| News | `search_news(query)`, `inspect_source_provenance`, `inspect_evidence_conflicts` | Locate relevant text, expose repeated provenance groups, identify contradictory source IDs and unknown/untrusted records |
| Financial Analyst | `compare_outflow_estimates`, `stress_test_outflows(multiplier)` | Explain missing-forecast fallback or disagreement with daily-rate estimates; inspect hypothetical cash demand at 1..3 times baseline |
| Treasury | `inspect_funding_effect`, `inspect_reporting_requirements`, `inspect_execution_requirements` | Check the candidate's remaining cash gap, reporting flag/draft fields, and proposal/approval blockers |

Diagnostics use host-bound fictional inputs. Literal search is not semantic retrieval;
provenance and stance remain designer metadata. A stress test does not replace the
baseline funding target or increase recommendation bounds. Treasury projections
assume immediate funding and cannot see private ledger approvals or cumulative
remaining capacity. Reports are never sent. Approval and execution stay host-only.

Example successful paths within four calls (followed by a final response):

- News: retrieve sources -> inspect provenance -> inspect conflicts -> verify claim.
- Financial: compare forecasts -> stress test -> build financial report -> final.
- Treasury: inspect funding effect -> inspect reporting -> inspect execution requirements -> prepare plan.

These paths are exercised with scripted/mock responses. They demonstrate dispatch,
budget and safety contracts, not improved live-model success rates.

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
- The secondary line returns reports only, with no combined decision or score. News, Financial Analyst and Treasury preparation each use up to six model turns by default. Risk uses one interpretation call. Compliance uses up to three model turns and three hybrid retrieval calls per proposed action. Treasury execution uses no model call. Complete-run costs depend on the trajectories, retrieval availability and number of proposals; mock runs are not evidence of LLM performance.

Run checks from the repository root:

```powershell
.\frontend\venv\Scripts\python.exe -B -m unittest discover -s frontend -p "test_*.py" -v
```

See [Financial Analyst ReAct and numeric grounding](../../docs/FINANCIAL_ANALYST.md) for its revised final-response protocol, budgets and diagnostic fields.
