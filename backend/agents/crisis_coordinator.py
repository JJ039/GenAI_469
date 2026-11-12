"""Build the combined team report from specialist evidence and validation results."""
from backend.agents.output_schema import HermesBankDecision


def build_team_report(reports, proposal, blockers):
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
    recommendation = financial.get('recommendation') or {}
    summary = (f"News assessment: {news.get('news_label', 'unverified')}. "
               f"Team decision: {selected['action']} for {selected['amount']} scenario units. ")
    summary += ('Review required. ' + ' '.join(reasons) if reasons else
                'The selected risk-ranked candidate passed simulation and regulatory compliance review. '
                'Treasury preparation is available for host review.')
    decision = HermesBankDecision(
        news_label=news.get('news_label', 'unverified'), **selected,
        confidence=recommendation.get('confidence', 0.0) if not reasons else 0.0,
        rationale=summary[:4000], needs_review=bool(reasons),
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
            'combination_policy': 'Validated risk-ranked candidate with compliance clearance; hold for incomplete evidence.'}
