"""Build the combined team report from specialist evidence and validation results."""
from backend.agents.output_schema import HermesBankDecision


def build_team_report(reports, proposal, blockers, *, compliance_basis=None):
    reasons = list(blockers)
    for name in ('news_verification', 'financial_analyst', 'risk_manager'):
        output = reports[name]
        if output.get('status') != 'completed':
            reasons.append(name.replace('_', ' ') + ': ' +
                           (output.get('reason') or 'Specialist analysis requires review.'))
    news = reports['news_verification'].get('report', {})
    financial = reports['financial_analyst']
    risk = reports['risk_manager'].get('report', {})
    outcomes = risk.get('candidate_outcomes', [])
    if proposal and not any(item.get('proposal') == proposal and item.get('feasible') is True
                            for item in outcomes):
        reasons.append('Risk results do not confirm the selected proposal is feasible.')
    selected = proposal if proposal and not reasons else {'action': 'hold', 'amount': 0}
    scenario_fallback = compliance_basis == 'scenario_limits_only'
    review_required = bool(reasons) or scenario_fallback
    recommendation = financial.get('recommendation') or {}
    summary = (f"News assessment: {news.get('news_label', 'unverified')}. "
               f"Team decision: {selected['action']} for {selected['amount']} scenario units. ")
    if reasons:
        summary += 'Review required. ' + ' '.join(reasons)
    elif scenario_fallback:
        summary += ('No determinate regulatory finding was available from the corpus. '
                    'The proposal passed the scenario-defined limits only; this is not regulatory '
                    'clearance and requires regulatory review. Treasury preparation is available '
                    'for host review.')
    else:
        summary += ('The selected risk-ranked candidate passed simulation and regulatory compliance review. '
                    'Treasury preparation is available for host review.')
    decision = HermesBankDecision(
        news_label=news.get('news_label', 'unverified'), **selected,
        confidence=recommendation.get('confidence', 0.0) if not review_required else 0.0,
        rationale=summary[:4000], needs_review=review_required,
        untrusted_content_flagged=bool(news.get('instruction_like_content_present')),
    ).model_dump()
    sections = []
    for name, output in reports.items():
        sections.append({'agent': name, 'status': output.get('status'),
                         'reason': output.get('reason'),
                         'findings': output.get('report', output.get('metrics', {})),
                         'interpretation': output.get('interpretation')})
    return {'summary': summary, 'decision': decision, 'blockers': reasons,
            'sections': sections, 'execution_authorized': False,
            'compliance_basis': compliance_basis,
            'regulatory_review_required': scenario_fallback,
            'combination_policy': 'Use the risk-ranked candidate only when scenario checks pass and no supported regulatory prohibition is found; when corpus review is indeterminate, report a scenario-limits-only decision requiring regulatory review.'}
