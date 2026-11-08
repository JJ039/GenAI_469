# Current experiment status

The baseline is a standalone LLM decision scored with the shared version-2 rubric.
The secondary line currently collects News Verification, Financial Analyst, Risk
Manager, Compliance Officer and Treasury Operations reports. A teammate owns the
combined-decision and approval stage; that implementation is deliberately absent.

## Current flow and integration boundary

1. News Verification computes its controlled-evidence verdict and LLM interpretation.
2. Financial Analyst computes metrics and a bounded funding recommendation.
3. Risk Manager reviews the actual financial recommendation and candidate actions.
4. Compliance Officer checks that recommendation, without selecting a team strategy.
5. Treasury Operations returns awaiting_authorization. No dashboard approval is issued.

`run_system(..., system="multi_agent")` retains its existing entry-point name for
compatibility. Its result has `decision_status="awaiting_integration"`, agent reports,
trace and usage telemetry. It has no decision or proposed_decision. Final outcome
metrics and scores are null, not zero or failures. Paired score tests and pass^k
exclude this unfinished decision line. Report failures are counted separately.
The removed decision-level compliance ablation is not exposed as a runnable variant.

## Retained evaluation support

The 13 version-2 scenarios, canonical action schema, evidence fixtures, injection
cases, financial references and compliance probes are retained. Answer keys never
reach the model. Baseline scoring still uses +1 for the news label, +3 ideal / +2
acceptable / -2 forbidden action, +2 amount in range, and a confidence contribution
of +confidence for a completely correct decision or -2*confidence otherwise.
Maximum score is 7. Missing required data require explicit deferral. Funding target
ranges allow +/-10% around action-specific targets, capped by simulation limits.

The shared runner saves manifests, exact scenario snapshots, prompts, raw outputs,
CSV metrics and per-agent diagnostics. It controls the same model, temperature,
output budget and requested reasoning effort for both lines. Baseline failures
remain in reliability denominators. Missing cost/token information remains null.
The baseline's repeated-run consistency and pass^k still work. Token and latency
comparisons are operational diagnostics, not evidence of secondary decision quality.

News sources are synthetic records with designer-labelled provenance and stance,
not live retrieval. Risk is a cash coverage proxy. `max_drawal_rate_pct` remains
explicitly unmodelled. No real funds move. The standalone Treasury ledger still
supports host-issued human approvals, exact binding and idempotent simulation,
but it is not invoked by the report pipeline.

## Teammate handoff

Use the agent reports and the financial recommendation as integration inputs.
Keep the baseline independent. Add the final proposal, Compliance review of that
proposal, explicit host approval and Treasury invocation in the teammate-owned
stage before re-enabling final secondary scores or decision-level ablation.
An independent human or optional LLM judge can assess rationale quality; it should
not replace the deterministic answer key or serve as the decision-making agent.

After integration, freeze the suite and run the real repeated comparison. Review
rationales and all injection cases manually. A concrete future experiment is to
replace stance-labelled fixtures with controlled raw documents and evaluate
handling of conflicting evidence on held-out cases.
