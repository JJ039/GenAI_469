"""Offline planted-error benchmark; no LLM requests or performance claims."""
from copy import deepcopy
from datetime import datetime, timezone
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from backend.agents.financial_react import execute_financial_tool
from backend.scenarios.validation import load_scenarios
from tools.financial_validation import check_financial_hallucinations


def benchmark(scenarios):
    cases, skipped = [], []
    for scenario in scenarios:
        try:
            report = execute_financial_tool('build_financial_report',{},scenario)
        except (KeyError,ValueError,TypeError):
            skipped.append(scenario['id'])
            continue
        observations = [{'id':'obs_report','ok':True,'result':report,'tool':'build_financial_report'}]
        gap = report['funding_gap']
        claim = {'metric':'funding_gap','value':gap,'unit':'amount','observation_id':'obs_report'}
        decision = {'recommendation':'hold','amount':0,'confidence':0.5,'rationale':f'Funding gap is {gap}.'}
        examples = [('valid_amount',False,deepcopy(decision),[deepcopy(claim)])]
        scaled = deepcopy(decision);scaled['rationale']=f'Funding gap is {gap/1000000}M.'
        examples.append(('valid_scaled_amount',False,scaled,[{**claim,'value':gap/1000000,'unit':'million'}]))
        wrong = gap + max(1,abs(gap)*0.25)
        examples.append(('wrong_cited_value',True,deepcopy(decision),[{**claim,'value':wrong}]))
        prose = deepcopy(decision);prose['rationale']=f'Funding gap is {wrong}.'
        examples.append(('wrong_rationale_value',True,prose,[deepcopy(claim)]))
        examples.append(('fabricated_citation',True,deepcopy(decision),[{**claim,'observation_id':'invented'}]))
        lcr = deepcopy(decision);lcr['rationale']+=' This is regulatory LCR.'
        examples.append(('unsupported_regulatory_claim',True,lcr,[deepcopy(claim)]))
        ratio = report['liquidity_capital_proxy']
        if ratio is not None:
            percentage = deepcopy(decision);percentage['rationale']=f'The liquidity/capital proxy is {ratio*100}%.'
            examples.append(('valid_percentage',False,percentage,[{'metric':'liquidity_capital_proxy','value':ratio*100,'unit':'percent','observation_id':'obs_report'}]))
        for name,expected,proposal,claims in examples:
            check=check_financial_hallucinations(proposal,claims,observations)
            cases.append({'scenario_id':scenario['id'],'case':name,'expected_flag':expected,
                          'flagged':not check['passed'],'flags':check['flags']})
    tp=sum(c['expected_flag'] and c['flagged'] for c in cases)
    fp=sum(not c['expected_flag'] and c['flagged'] for c in cases)
    tn=sum(not c['expected_flag'] and not c['flagged'] for c in cases)
    fn=sum(c['expected_flag'] and not c['flagged'] for c in cases)
    return {'scope':'Synthetic planted-error/citation checks, NOT measured LLM hallucination rates',
            'cases':len(cases),'skipped_missing_data':skipped,
            'true_positives':tp,'false_positives':fp,'true_negatives':tn,'false_negatives':fn,
            'precision':tp/(tp+fp) if tp+fp else None,'recall':tp/(tp+fn) if tp+fn else None,
            'false_positive_rate':fp/(fp+tn) if fp+tn else None,'case_results':cases}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'results/financial_guardrails')
    args=parser.parse_args()
    report=benchmark([s for _,s in load_scenarios(ROOT/'backend/scenarios/scenarios')])
    args.output.mkdir(parents=True,exist_ok=True)
    path=args.output/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'.json')
    path.write_text(json.dumps(report,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='case_results'},indent=2))
    print('Saved:',path)


if __name__=='__main__':
    main()
