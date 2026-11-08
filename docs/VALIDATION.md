# Implementation validation and pilot reflection

These checks validate the implementation. They are not the final five-repeat
research study and do not establish that multi-agent systems outperform a baseline.

## What worked

- A 195-run deterministic integration check exercised all 13 scenarios, five
  repeats, and baseline / multi-agent / compliance-ablation variants. It verified
  orchestration and artifact generation only. Its outputs are watermarked mock.
- The revised live smoke check used Nemotron through OpenRouter on two scenarios,
  one repeat each for baseline and multi-agent. All four runs completed with correct
  decisions under their snapshotted rubric. The healthy-bank multi-agent run held
  with zero funding; the stress case proposed a 13.2M facility draw and completed
  a host-approved in-memory Treasury simulation.
- Adversarial regression checks preserve an oversized coordinator proposal, block
  it at the host gate, and show the same proposal remaining visible in the compliance
  ablation. Treasury's minimum boundary blocks execution in the ablation too.
- Raw model failures and partial reports are retained, rather than replaced with
  fabricated fallback decisions. Token/cost data are preserved for empty content
  when the provider supplies usage.

## What initially did not work, and why

The first live pilot returned an empty baseline response for the stress scenario.
It also returned otherwise reasonable secondary decisions with `needs_review=true`
for both scenarios: the coordinator conflated routine approval/reporting with
missing essential data. The pilot was retained under `results/live_smoke/`.

The prompts now define `needs_review` explicitly and make clear that the host
handles routine simulation approval and reporting. The request budget was raised
from 2400 to 4096 with requested reasoning effort low. Empty content remains a
measured failure, not a hidden retry. The subsequent smoke check succeeded, but
this small before/after pilot does not identify which change caused improvement.

The original runner also deleted its scoring answer key and mixed action labels.
Those software defects could produce misleading scores regardless of model quality.
Both dashboard and CLI now use one engine and evaluator, and the suite is versioned.

## Pilot efficiency observations

Revised live smoke snapshot: `results/live_smoke_after/20261108T070804954075Z`.

| Scenario | System | Seconds | Input tokens | Output tokens | Correct |
| --- | --- | ---: | ---: | ---: | ---: |
| scn_001 healthy | Baseline | 19.6 | 611 | 1401 | Yes |
| scn_001 healthy | Multi-agent | 63.6 | 5069 | 4880 | Yes |
| scn_002 stress | Baseline | 31.5 | 614 | 1655 | Yes |
| scn_002 stress | Multi-agent | 104.8 | 5211 | 4020 | Yes |

The provider reported zero cost for these free-endpoint calls; this is not a
promise about future model pricing. Multi-agent calls consumed more tokens and
wall-clock time, while this tiny sample showed no decision-quality advantage.
Output tokens include provider-counted reasoning where applicable. These pilot
runs preceded subsequent reporting-only changes; manifests and prompts preserve
which implementation produced each result.

## Remaining research work and future direction

Run the real repeated study with a frozen final suite and complete the human
rationale/injection review. Synthetic source records currently expose designer-
labelled stance and trust equally to both systems; this tests controlled evidence
aggregation, not independent credibility assessment or open-web fact checking.
The financial/risk models also omit interest, contagion, execution delays and
unmodelled regulatory fields. Conclusions must stay within those limits.

A concrete next experiment is to replace stance-labelled source fixtures with
independently authored raw documents and evidence citations, then evaluate whether
coordinator disagreement handling improves decisions on held-out conflicting-news
cases without increasing unsafe funding. This would make verification harder and
reduce the chance that apparent accuracy comes from explicit fixture labels.
