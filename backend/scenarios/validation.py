"""Authoring consistency checks before any evaluation requests are made."""
import json
from math import isfinite
from tools.news_tools import verify_claim
from tools.compliance_tools import ACTIONS, retrieve_regulations


def load_scenarios(directory):
    scenarios = []
    ids = set()
    for path in sorted(directory.glob('scn_*.json')):
        scenario = json.loads(path.read_text(encoding='utf-8'))
        validate_scenario(scenario)
        if scenario['id'] in ids:
            raise ValueError('Duplicate scenario id: ' + scenario['id'])
        ids.add(scenario['id'])
        scenarios.append((path, scenario))
    if not scenarios:
        raise ValueError('No scenarios found')
    return scenarios


def validate_scenario(scenario):
    for key in ('id','trigger','financials','regulations','news_sources','answer_key'):
        if key not in scenario:
            raise ValueError('Scenario missing ' + key)
    if not isinstance(scenario['financials'],dict):
        raise ValueError('financials must be an object')
    for field,value in scenario['financials'].items():
        if field not in ('capital','liquidity','borrowing_limit','daily_withdrawals','forecast_next_7d'):
            continue
        if field == 'forecast_next_7d' and value is None:
            continue
        try:
            valid = not isinstance(value,bool) and isinstance(value,(int,float)) and isfinite(value) and value >= 0
        except OverflowError:
            valid = False
        if not valid:
            raise ValueError('Invalid financial value: ' + field)
    retrieve_regulations(scenario)
    key = scenario['answer_key']
    if not isinstance(key.get('needs_review'),bool):
        raise ValueError('Answer key needs_review must be boolean')
    if verify_claim(scenario)['news_label'] != key['news_label']:
        raise ValueError('News evidence conflicts with answer key: ' + scenario['id'])
    for field in ('ideal_actions','acceptable_actions','forbidden_actions'):
        if not isinstance(key[field], list) or any(a not in ACTIONS for a in key[field]):
            raise ValueError('Noncanonical action in ' + field)
    acceptable = set(key['ideal_actions'] + key['acceptable_actions'])
    if not key['ideal_actions'] or acceptable & set(key['forbidden_actions']):
        raise ValueError('Inconsistent action sets')
    for action in acceptable:
        bounds = key.get('target_amount_ranges', {}).get(action, key['target_amount_range'])
        if len(bounds) != 2 or any(not isinstance(v, (int,float)) or not isfinite(v) for v in bounds) or not 0 <= bounds[0] <= bounds[1]:
            raise ValueError('Invalid target amount range')
        if action == 'hold' and bounds != [0,0]:
            raise ValueError('Hold answer must use amount 0')
    missing = any(k not in scenario['financials'] or scenario['financials'][k] is None for k in ('capital','liquidity','borrowing_limit','daily_withdrawals'))
    if missing and not key.get('needs_review'):
        raise ValueError('Missing financials must require review')
