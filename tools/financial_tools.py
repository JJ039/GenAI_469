"""Deterministic calculations for synthetic bank-crisis scenarios.
All monetary amounts use the scenario's currency units.
"""
from math import isfinite
from copy import deepcopy


def get_bank_financials(scenario):
    f = scenario['financials']
    if not isinstance(f, dict):
        raise ValueError('financials must be an object')
    required = ('capital', 'liquidity', 'borrowing_limit', 'daily_withdrawals')
    out = {}
    for key in required:
        if isinstance(f[key], bool) or not isinstance(f[key], (int, float)):
            raise ValueError(f'{key} must be numeric')
        value = float(f[key])
        if not isfinite(value) or value < 0:
            raise ValueError(f'{key} must be a finite non-negative number')
        out[key] = value
    if 'forecast_next_7d' in f and f['forecast_next_7d'] is not None:
        if isinstance(f['forecast_next_7d'], bool) or not isinstance(f['forecast_next_7d'], (int, float)):
            raise ValueError('forecast_next_7d must be numeric')
        value = float(f['forecast_next_7d'])
        if not isfinite(value) or value < 0:
            raise ValueError('forecast_next_7d must be non-negative')
        out['forecast_next_7d'] = value
    return out


def calculate_liquidity_ratio(financials):
    """Liquidity/capital proxy, NOT regulatory LCR."""
    capital = financials['capital']
    return None if capital == 0 else financials['liquidity'] / capital


def forecast_cash_outflow(financials, days=7):
    """Use supplied 7-day total when available, otherwise daily rate * days.
    Assumes supplied forecast is total over seven days, not per-day.
    """
    if isinstance(days, bool) or not isinstance(days, int) or days <= 0:
        raise ValueError('days must be a positive integer')
    if days == 7 and 'forecast_next_7d' in financials:
        return financials['forecast_next_7d']
    return financials['daily_withdrawals'] * days


def calculate_funding_gap(financials, forecast_outflow, reserve_buffer=0):
    if reserve_buffer < 0:
        raise ValueError('reserve_buffer must be non-negative')
    return max(0.0, forecast_outflow + reserve_buffer - financials['liquidity'])


def calculate_cash_runway(financials):
    daily = financials['daily_withdrawals']
    return None if daily == 0 else financials['liquidity'] / daily


def calculate_borrowing_capacity(scenario):
    """Largest single funding channel in the simulation, never authorization."""
    financials = get_bank_financials(scenario)
    regulatory_limit = float(scenario.get('regulations', {}).get('max_draw_facility', 0))
    if not isfinite(regulatory_limit) or regulatory_limit < 0:
        raise ValueError('max_draw_facility must be finite and non-negative')
    allowed = scenario.get('regulations', {}).get('allowed_actions', ['hold','borrow_interbank','draw_central_bank_facility'])
    return max(financials['borrowing_limit'] if 'borrow_interbank' in allowed else 0,
               regulatory_limit if 'draw_central_bank_facility' in allowed else 0)


def build_financial_report(scenario):
    f = get_bank_financials(scenario)
    outflow = forecast_cash_outflow(f)
    gap = calculate_funding_gap(f, outflow)
    capacity = calculate_borrowing_capacity(scenario)
    facility = float(scenario.get('regulations', {}).get('max_draw_facility', 0))
    capacities = {'hold': 0.0, 'borrow_interbank': f['borrowing_limit'], 'draw_central_bank_facility': facility}
    allowed = scenario.get('regulations', {}).get('allowed_actions', list(capacities))
    capacities = {action: limit if action in allowed else 0 for action, limit in capacities.items()}
    suggested = {action: min(gap, limit) for action, limit in capacities.items()}
    return {
        'scenario_id': scenario.get('id'),
        'liquidity_capital_proxy': calculate_liquidity_ratio(f),
        'forecast_7d_outflow': outflow,
        'cash_runway_days': calculate_cash_runway(f),
        'funding_gap': gap,
        'borrowing_capacity': capacity,
        'funding_shortfall_after_borrowing': max(0.0, gap - capacity),
        'funding_capacity_by_action': capacities,
        'suggested_funding_by_action': suggested,
        'suggested_funding_amount': max(suggested.values()),
        'forecast_source': 'scenario_forecast' if 'forecast_next_7d' in f else 'daily_rate_extrapolation',
        'assumptions': ['Forecast next 7d interpreted as total seven-day cash outflow',
                        'No new inflows or asset sales included',
                        'Borrowing capacity is not authorisation'],
    }


def compare_outflow_estimates(scenario):
    data = get_bank_financials(scenario)
    supplied = data.get('forecast_next_7d')
    extrapolated = data['daily_withdrawals'] * 7
    return {'supplied_7d_forecast': supplied, 'daily_rate_7d_estimate': extrapolated,
            'selected_7d_forecast': forecast_cash_outflow(data),
            'forecast_difference': None if supplied is None else supplied-extrapolated,
            'forecast_source': 'daily_rate_extrapolation' if supplied is None else 'scenario_forecast',
            'assumption': 'Daily-rate estimate assumes constant withdrawals and no new inflows; the supplied seven-day forecast remains authoritative when present.'}

def stress_test_outflows(scenario, multiplier):
    if isinstance(multiplier, bool) or not isinstance(multiplier, (int, float)) or not isfinite(multiplier) or not 1 <= multiplier <= 3:
        raise ValueError('multiplier must be a finite number between 1 and 3')
    data = get_bank_financials(scenario)
    baseline = forecast_cash_outflow(data)
    stressed = baseline * multiplier
    return {'baseline_7d_outflow': baseline, 'stress_multiplier': multiplier,
            'stressed_7d_outflow': stressed,
            'baseline_funding_gap': max(0, baseline-data['liquidity']),
            'stressed_funding_gap': max(0, stressed-data['liquidity']),
            'hypothetical': True,
            'limitation': 'Sensitivity analysis only; does not replace the baseline funding target, grant authority or change scenario limits.'}


# Instrument actual tool invocations, including nested deterministic calculations.
from backend.telemetry import tracked_tool
for _name, _value in list(globals().items()):
    if callable(_value) and getattr(_value, '__module__', None) == __name__ and not _name.startswith('_') and not isinstance(_value, type):
        globals()[_name] = tracked_tool(_value)


TOOL_CATALOG = [
    {"name": "get_bank_financials", "arguments": {}, "description": "Read trusted capital, liquidity, borrowing limit, daily withdrawals and optional forecast."},
    {"name": "calculate_liquidity_ratio", "arguments": {}, "description": "Return liquidity_capital_proxy (ratio, not regulatory LCR)."},
    {"name": "forecast_cash_outflow", "arguments": {"days": "optional integer 1..30; default 7"}, "description": "Compute forecast_outflow and forecast_horizon_days. A supplied forecast is a seven-day total."},
    {"name": "calculate_funding_gap", "arguments": {}, "description": "Return funding_gap for seven days and forecast_7d_outflow."},
    {"name": "calculate_cash_runway", "arguments": {}, "description": "Return cash_runway_days, or null when withdrawals are zero."},
    {"name": "calculate_borrowing_capacity", "arguments": {}, "description": "Return largest permitted single-channel borrowing_capacity."},
    {"name": "build_financial_report", "arguments": {}, "description": "Full trusted report, including action-specific suggested funding. Required before final response."},
    {"name": "compare_outflow_estimates", "arguments": {}, "description": "Compare supplied seven-day forecast with daily withdrawals extrapolation; show missing forecast and fallback assumptions."},
    {"name": "stress_test_outflows", "arguments": {"multiplier": "required finite number 1..3"}, "description": "Hypothetical seven-day outflow sensitivity. Does not change the baseline funding target or permitted recommendation amount."}
]


def execute_financial_tool(name, arguments, scenario):
    """No arbitrary dispatch, execution, input replacement, or model-supplied figures."""
    if not isinstance(name, str) or name not in {tool['name'] for tool in TOOL_CATALOG}:
        raise ValueError('Unknown or disallowed financial tool')
    if not isinstance(arguments, dict):
        raise ValueError('Tool arguments must be an object')
    allowed = {'days'} if name == 'forecast_cash_outflow' else {'multiplier'} if name == 'stress_test_outflows' else set()
    if set(arguments) - allowed:
        raise ValueError('Unexpected arguments; financial inputs are supplied only by the host')
    scenario = deepcopy(scenario)
    if name == 'compare_outflow_estimates':
        return compare_outflow_estimates(scenario)
    if name == 'stress_test_outflows':
        if set(arguments) != {'multiplier'}:
            raise ValueError('stress_test_outflows requires multiplier')
        return stress_test_outflows(scenario, arguments['multiplier'])
    if name == 'get_bank_financials':
        return get_bank_financials(scenario)
    if name == 'build_financial_report':
        return {**build_financial_report(scenario), 'forecast_horizon_days': 7}
    if name == 'calculate_borrowing_capacity':
        return {'borrowing_capacity': calculate_borrowing_capacity(scenario)}
    data = get_bank_financials(scenario)
    if name == 'calculate_liquidity_ratio':
        return {'liquidity_capital_proxy': calculate_liquidity_ratio(data)}
    if name == 'forecast_cash_outflow':
        days = arguments.get('days', 7)
        if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= 30:
            raise ValueError('days must be an integer between 1 and 30')
        output = {'forecast_outflow': forecast_cash_outflow(data, days), 'forecast_horizon_days': days}
        if days == 7:
            output['forecast_7d_outflow'] = output['forecast_outflow']
        return output
    if name == 'calculate_funding_gap':
        outflow = forecast_cash_outflow(data)
        return {'funding_gap': calculate_funding_gap(data, outflow),
                'forecast_7d_outflow': outflow, 'forecast_horizon_days': 7}
    if name == 'calculate_cash_runway':
        return {'cash_runway_days': calculate_cash_runway(data)}
    raise ValueError('Unsupported financial tool')


# Mandatory host-side recommendation validation; not a model-selectable tool.
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
        # A stated forecast horizon is metadata, not the nearby financial metric.
        after = rationale[match.end():match.end()+20].lower()
        horizon_after = re.match(
            r'\s*-?\s*days?\s+(?:horizon|period|window|time\s+frame|timeframe)\b',
            after,
        )
        horizon_before = re.search(
            r'\b(?:over|across|within|for)\s+(?:the\s+)?$',
            prefix,
        )
        day_phrase = suffix in ('day', 'days') or re.match(
            r'\s*-\s*days?\b', after
        )
        if day_phrase and (
            horizon_after or horizon_before or
            (re.match(r'\s*-?\s*day', after) and
             ('forecast' in context or 'outflow' in context))
        ):
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
