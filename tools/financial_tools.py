"""Deterministic calculations for synthetic bank-crisis scenarios.
All monetary amounts use the scenario's currency units.
"""
from math import isfinite


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


# Instrument actual tool invocations, including nested deterministic calculations.
from backend.telemetry import tracked_tool
for _name, _value in list(globals().items()):
    if callable(_value) and getattr(_value, '__module__', None) == __name__ and not _name.startswith('_') and not isinstance(_value, type):
        globals()[_name] = tracked_tool(_value)
