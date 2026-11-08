"""Allowlisted financial tools bound to immutable host inputs, never model inputs."""
from copy import deepcopy
from tools import financial_tools as financial

TOOL_CATALOG = [
    {"name": "get_bank_financials", "arguments": {}, "description": "Read trusted capital, liquidity, borrowing limit, daily withdrawals and optional forecast."},
    {"name": "calculate_liquidity_ratio", "arguments": {}, "description": "Return liquidity_capital_proxy (ratio, not regulatory LCR)."},
    {"name": "forecast_cash_outflow", "arguments": {"days": "optional integer 1..30; default 7"}, "description": "Compute forecast_outflow and forecast_horizon_days. A supplied forecast is a seven-day total."},
    {"name": "calculate_funding_gap", "arguments": {}, "description": "Return funding_gap for seven days and forecast_7d_outflow."},
    {"name": "calculate_cash_runway", "arguments": {}, "description": "Return cash_runway_days, or null when withdrawals are zero."},
    {"name": "calculate_borrowing_capacity", "arguments": {}, "description": "Return largest permitted single-channel borrowing_capacity."},
    {"name": "build_financial_report", "arguments": {}, "description": "Full trusted report, including action-specific suggested funding. Required before final response."}
]


def execute_financial_tool(name, arguments, scenario):
    """No arbitrary dispatch, execution, input replacement, or model-supplied figures."""
    if not isinstance(name, str) or name not in {tool['name'] for tool in TOOL_CATALOG}:
        raise ValueError('Unknown or disallowed financial tool')
    if not isinstance(arguments, dict):
        raise ValueError('Tool arguments must be an object')
    allowed = {'days'} if name == 'forecast_cash_outflow' else set()
    if set(arguments) - allowed:
        raise ValueError('Unexpected arguments; financial inputs are supplied only by the host')
    scenario = deepcopy(scenario)
    if name == 'get_bank_financials':
        return financial.get_bank_financials(scenario)
    if name == 'build_financial_report':
        return {**financial.build_financial_report(scenario), 'forecast_horizon_days': 7}
    if name == 'calculate_borrowing_capacity':
        return {'borrowing_capacity': financial.calculate_borrowing_capacity(scenario)}
    data = financial.get_bank_financials(scenario)
    if name == 'calculate_liquidity_ratio':
        return {'liquidity_capital_proxy': financial.calculate_liquidity_ratio(data)}
    if name == 'forecast_cash_outflow':
        days = arguments.get('days', 7)
        if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= 30:
            raise ValueError('days must be an integer between 1 and 30')
        output = {'forecast_outflow': financial.forecast_cash_outflow(data, days), 'forecast_horizon_days': days}
        if days == 7:
            output['forecast_7d_outflow'] = output['forecast_outflow']
        return output
    if name == 'calculate_funding_gap':
        outflow = financial.forecast_cash_outflow(data)
        return {'funding_gap': financial.calculate_funding_gap(data, outflow),
                'forecast_7d_outflow': outflow, 'forecast_horizon_days': 7}
    if name == 'calculate_cash_runway':
        return {'cash_runway_days': financial.calculate_cash_runway(data)}
    raise ValueError('Unsupported financial tool')
