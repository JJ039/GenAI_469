# Validation status after separating team responsibilities

The combined-decision and automatic approval implementation has been removed at
the user's request. The baseline, all five specialist roles, scenario suite,
model client, deterministic tools and logging remain.

Current regression checks verify that the specialist pipeline returns reports,
passes the Financial Analyst recommendation into Risk and Compliance, never
issues approval, leaves Treasury awaiting authorization, and assigns no final
secondary decision score. Baseline evaluation and output-validation checks remain.
The frontend identifies completed specialist reports as awaiting integration.

Historical pilot artifacts under results/live_smoke and results/live_smoke_after
belong to the earlier removed integration. They are retained as historical data,
not claims about the current report-only implementation. No new live inference
is needed for removal verification; mocked tests do not consume provider quota.

A complete baseline-versus-team research comparison and decision-level guardrail
ablation must wait for the teammate-owned integration. Run instructions and
current interfaces are documented in the root README and docs/EXPERIMENT.md.
