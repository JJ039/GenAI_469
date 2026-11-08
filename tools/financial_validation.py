"""Numeric financial grounding checks against actual host-generated observations.

Flags are suspected hallucinations or provenance errors, not a semantic proof.
Numbers in prose use metric aliases and local context; manual review remains useful.
"""
from math import isfinite, isclose
import re

AMOUNT_UNITS = {'amount': 1, 'thousand': 1000, 'million': 1000000, 'billion': 1000000000}
RATIO_METRICS = {'liquidity_capital_proxy'}
DAY_METRICS = {'cash_runway_days', 'forecast_horizon_days'}
ALIASES = {
    'liquidity_capital_proxy': r'liquidity\s*[/\-]\s*capital(?:\s+proxy)?|liquidity(?:[ -]to[ -]capital)?\s+(?:ratio|proxy)|liquidity.capital proxy',
    'cash_runway_days': r'cash runway(?: days)?|runway(?: days)?',
    'forecast_horizon_days': r'forecast horizon',
    'forecast_7d_outflow': r'(?:forecast(?:ed)?(?:\s+(?:7.day|seven.day|cash))?\s+outflows?|outflow forecast)',
    'forecast_outflow': r'cash outflows?|outflows?',
    'funding_gap': r'funding gap|cash gap|shortfall',
    'daily_withdrawals': r'daily withdrawals?',
    'borrowing_capacity': r'borrowing capacity',
    'borrowing_limit': r'interbank limit|borrowing limit',
    'liquidity': r'liquidity(?!\s*(?:[/\-]|ratio|proxy|capital))',
    'capital': r'(?<!/)\bcapital\b(?!\s+proxy)'
}
NUMBER = re.compile(r'(?<![\w.])(?P<number>[-+]?\d[\d,]*(?:\.\d+)?(?:e[-+]?\d+)?|zero)\s*(?P<suffix>billion|million|thousand|bn|[kmb]|%|percent(?:age)?|days?)?(?!\w)', re.I)


def numeric(value):
    try:
        return not isinstance(value, bool) and isinstance(value, (int, float)) and isfinite(value)
    except OverflowError:
        return False


def flatten_numbers(value, prefix=''):
    values = {}
    if isinstance(value, dict):
        for key, item in value.items():
            path = f'{prefix}.{key}' if prefix else key
            values.update(flatten_numbers(item, path))
    elif numeric(value) or value is None:
        values[prefix] = value
    return values


def normalized(value, unit, metric):
    if not numeric(value):
        raise ValueError('Claim value must be a finite number')
    if metric in RATIO_METRICS:
        if unit not in ('ratio', 'percent'):
            raise ValueError('Ratio claims require ratio or percent units')
        return value / 100 if unit == 'percent' else value
    if metric in DAY_METRICS:
        if unit != 'days':
            raise ValueError('Time claims require days units')
        return value
    if unit not in AMOUNT_UNITS:
        raise ValueError('Amount claims require amount, thousand, million or billion units')
    result = value * AMOUNT_UNITS[unit]
    if not numeric(result):
        raise ValueError('Unit conversion overflow')
    return result


def matches(actual, expected):
    return numeric(actual) and numeric(expected) and isclose(actual, expected, rel_tol=0.005, abs_tol=0.0001)


def _metric_near(text, start, end, suffix):
    # Choose the closest metric phrase in the same clause; specific phrases win ties.
    boundary = re.compile(r';|\n|(?<!\d)\.(?!\d)|,\s+(?=[A-Za-z])|\b(?:and|while|but)\b', re.I)
    before = list(boundary.finditer(text[:start]))
    left = before[-1].end() if before else 0
    after = boundary.search(text[end:])
    right = end + after.start() if after else len(text)
    region_start, region_end = max(left, start - 45), min(right, end + 35)
    candidates = []
    for order, (metric, pattern) in enumerate(ALIASES.items()):
        for hit in re.finditer(pattern, text[region_start:region_end], re.I):
            a, b = region_start + hit.start(), region_start + hit.end()
            distance = start-b if b <= start else a-end if a >= end else 0
            candidates.append((max(0, distance), order, metric, a, b))
    if not candidates:
        return None
    preceding = [candidate for candidate in candidates if candidate[4] <= start]
    closest = min(preceding or candidates)
    # A raw capital word inside a ratio label should not relabel the ratio.
    for candidate in candidates:
        if candidate[2] == 'liquidity_capital_proxy' and candidate[3] <= closest[3] and candidate[4] >= closest[4]:
            return 'liquidity_capital_proxy'
    return closest[2]


def check_financial_hallucinations(decision, claims, observations):
    """Verify metric/value/unit/source claims and numeric assertions in rationale."""
    evidence = {o['id']: flatten_numbers(o['result']) for o in observations if o.get('ok')}
    available = {}
    for values in evidence.values():
        for path, value in values.items():
            available.setdefault(path, []).append(value)
    if 'forecast_outflow' not in available and 'forecast_7d_outflow' in available:
        available['forecast_outflow'] = available['forecast_7d_outflow']
    flags, verified = [], []
    if not isinstance(claims, list) or not claims:
        flags.append({'kind': 'missing_citations', 'location': 'claims', 'message': 'At least one cited numeric financial claim is required.'})
        claims = []
    if len(claims) > 32:
        flags.append({'kind':'too_many_claims','location':'claims','message':'At most 32 claims are supported.'})
        claims = claims[:32]
    for index, claim in enumerate(claims):
        location = f'claims[{index}]'
        if not isinstance(claim, dict) or set(claim) != {'metric', 'value', 'unit', 'observation_id'}:
            flags.append({'kind': 'invalid_claim', 'location': location})
            continue
        metric, source = claim['metric'], claim['observation_id']
        if not isinstance(metric, str) or not isinstance(source, str) or source not in evidence or metric not in evidence[source]:
            flags.append({'kind': 'unobserved_metric', 'location': location, 'message': 'The cited successful tool observation does not contain this metric.'})
            continue
        try:
            actual = normalized(claim['value'], claim['unit'], metric)
        except (ValueError, TypeError):
            flags.append({'kind': 'unit_or_value_error', 'location': location, 'metric': metric})
            continue
        expected = evidence[source][metric]
        if not matches(actual, expected):
            flags.append({'kind': 'value_mismatch', 'location': location, 'metric': metric,
                          'claimed_value': actual, 'observed_value': expected})
        else:
            verified.append({'metric': metric, 'value': actual})

    rationale = decision['rationale']
    mentions = list(NUMBER.finditer(rationale))
    for match in mentions:
        token, suffix = match.group('number'), (match.group('suffix') or '').lower()
        value = 0.0 if token.lower() == 'zero' else float(token.replace(',', ''))
        context = rationale[max(0, match.start()-30):min(len(rationale), match.end()+25)].lower()
        prefix = rationale[max(0, match.start()-20):match.start()].lower()
        metric = _metric_near(rationale, match.start(), match.end(), suffix)
        unit = {'k':'thousand','m':'million','b':'billion','bn':'billion','%':'percent','percent':'percent','percentage':'percent','day':'days'}.get(suffix, suffix or 'amount')
        if suffix in ('day','days'):
            unit = 'days'
        # A stated forecast horizon is metadata, not the cash outflow beside it.
        after = rationale[match.end():match.end()+20].lower()
        if re.match(r'\s*-?\s*day', after) and ('forecast' in context or 'outflow' in context):
            metric, unit = 'forecast_horizon_days', 'days'
        if 'confidence' in context and unit == 'percent' and metric is None:
            if not matches(value/100, decision['confidence']):
                flags.append({'kind':'confidence_mismatch','location':'rationale','text':match.group()})
            continue
        if metric in RATIO_METRICS and not suffix:
            unit = 'ratio'
        if metric in DAY_METRICS and not suffix:
            unit = 'days'
        expected_values = available.get(metric, []) if metric else [v for values in available.values() for v in values]
        # Explicitly proposed amounts may be smaller than the maximum suggested funding.
        proposed = any(word in prefix for word in ('recommend', 'propose', 'borrow', 'draw')) and metric != 'funding_gap'
        if proposed and unit in AMOUNT_UNITS and matches(value*AMOUNT_UNITS[unit], decision['amount']):
            continue
        try:
            actual = normalized(value, unit, metric or '')
        except ValueError:
            flags.append({'kind':'rationale_unit_mismatch','location':'rationale','text':match.group(),'metric':metric})
            continue
        comparator = ('ne' if re.search(r'(not|not equal to|!=)\s*$', prefix) else
                      'lt' if re.search(r'(under|less than|below|<)\s*$', prefix) else
                      'le' if re.search(r'(at most|no more than|<=)\s*$', prefix) else
                      'gt' if re.search(r'(over|more than|above|>)\s*$', prefix) else
                      'ge' if re.search(r'(at least|>=)\s*$', prefix) else None)
        def supported(expected):
            if not numeric(expected):
                return False
            return {'lt':lambda:expected<actual,'le':lambda:expected<=actual,
                    'gt':lambda:expected>actual,'ge':lambda:expected>=actual,'ne':lambda:not matches(actual,expected)}.get(comparator,lambda:matches(actual,expected))()
        if not any(supported(expected) for expected in expected_values):
            flags.append({'kind':'rationale_value_mismatch' if metric else 'unsupported_number',
                          'location':'rationale','text':match.group(),'metric':metric,'claimed_value':actual})
    for hit in re.finditer(r'\bLCR\b', rationale, re.I):
        if not re.search(r'\bnot(?:\s+\w+){0,3}\s*$', rationale[max(0,hit.start()-35):hit.start()], re.I):
            flags.append({'kind':'unsupported_regulatory_lcr','location':'rationale','message':'The liquidity/capital proxy is not regulatory LCR.'})
    return {'passed': not flags, 'claims_checked': len(claims), 'supported_claims': len(verified),
            'grounded_claim_rate': len(verified)/len(claims) if claims else 0.0,
            'rationale_numbers_checked': len(mentions), 'flag_count': len(flags), 'flags': flags,
            'relative_tolerance':0.005, 'absolute_tolerance':0.0001,
            'scope':'Numeric and citation checks only; local prose matching is heuristic and requires manual review.'}
