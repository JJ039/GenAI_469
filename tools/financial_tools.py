"""Deterministic calculations for synthetic bank-crisis scenarios.
All monetary amounts use the scenario's currency units.
"""
from math import isfinite


def get_bank_financials(scenario):
    f = scenario['financials']
    required = ('capital', 'liquidity', 'borrowing_limit', 'daily_withdrawals')
    out = {}
    for key in required:
        value = float(f[key])
        if not isfinite(value) or value < 0:
            raise ValueError(f'{key} must be a finite non-negative number')
        out[key] = value
    if 'forecast_next_7d' in f and f['forecast_next_7d'] is not None:
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
    if not isinstance(days, int) or days <= 0:
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
    """Conservative simulated limit; actual approvals are Compliance's job."""
    financials = get_bank_financials(scenario)
    regulatory_limit = float(scenario.get('regulations', {}).get('max_draw_facility', float('inf')))
    if regulatory_limit < 0:
        raise ValueError('max_draw_facility must be non-negative')
    return min(financials['borrowing_limit'], regulatory_limit)


def build_financial_report(scenario):
    f = get_bank_financials(scenario)
    outflow = forecast_cash_outflow(f)
    gap = calculate_funding_gap(f, outflow)
    capacity = calculate_borrowing_capacity(scenario)
    return {
        'scenario_id': scenario.get('id'),
        'liquidity_capital_proxy': calculate_liquidity_ratio(f),
        'forecast_7d_outflow': outflow,
        'cash_runway_days': calculate_cash_runway(f),
        'funding_gap': gap,
        'borrowing_capacity': capacity,
        'funding_shortfall_after_borrowing': max(0.0, gap - capacity),
        'suggested_funding_amount': min(gap, capacity),
        'forecast_source': 'scenario_forecast' if 'forecast_next_7d' in f else 'daily_rate_extrapolation',
        'assumptions': ['Forecast next 7d interpreted as total seven-day cash outflow',
                        'No new inflows or asset sales included',
                        'Borrowing capacity is not authorisation'],
    }
