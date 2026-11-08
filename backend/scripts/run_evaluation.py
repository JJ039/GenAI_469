"""Run the same scenario suite against baseline and coordinated systems."""
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import random
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from backend.llm_client import LLMClient, DEFAULT_MODEL
from backend.mock_client import MockClient
from backend.systems import run_system
from backend.scenarios.validation import load_scenarios
from backend.reporting import aggregate, reflection_markdown


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runs', type=int, default=5)
    parser.add_argument('--systems', nargs='+', choices=['baseline','multi_agent','multi_agent_no_compliance'], default=['baseline','multi_agent','multi_agent_no_compliance'])
    parser.add_argument('--model', default=None)
    parser.add_argument('--temperature', type=float, default=0.1)
    parser.add_argument('--transport', choices=['openrouter','hermes'], default='openrouter')
    parser.add_argument('--max-tokens', type=int, default=4096)
    parser.add_argument('--reasoning-effort', choices=['none','minimal','low','medium','high'], default='low')
    parser.add_argument('--scenarios', type=Path, default=ROOT/'backend/scenarios/scenarios')
    parser.add_argument('--output', type=Path, default=ROOT/'results/evaluation')
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--mock', action='store_true', help='Deterministic integration fixture; NOT research results')
    parser.add_argument('--limit', type=int, default=None, help='Optional small smoke-check subset')
    args = parser.parse_args(argv)
    if args.runs < 1 or (args.limit is not None and args.limit < 1):
        parser.error('runs and limit must be positive')
    if len(set(args.systems)) != len(args.systems):
        parser.error('systems must be unique')
    if args.transport == 'hermes' and not args.mock:
        parser.error('Controlled experiments require openrouter transport to set temperature and disable external tools; Hermes remains available for dashboard/manual use.')
    scenarios = load_scenarios(args.scenarios)
    if args.limit:
        scenarios = scenarios[:args.limit]
    client = MockClient() if args.mock else LLMClient(args.model, args.temperature, args.transport, max_tokens=args.max_tokens, reasoning_effort=args.reasoning_effort)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    output = args.output / (('MOCK_' if args.mock else '') + stamp)
    output.mkdir(parents=True, exist_ok=False)
    snapshot = [s for _,s in scenarios]
    snapshot_text = json.dumps(snapshot,sort_keys=True,indent=2)
    (output/'scenarios.json').write_text(snapshot_text,encoding='utf-8')
    sources = sorted(list((ROOT/'backend').rglob('*.py')) + list((ROOT/'tools').glob('*.py')))
    implementation_hash = hashlib.sha256(''.join(str(p.relative_to(ROOT)) + ':' + hashlib.sha256(p.read_bytes()).hexdigest() for p in sources).encode()).hexdigest()
    manifest = {'generated_at':stamp,'mock':args.mock,'model':client.model,'transport':client.transport,
                'temperature':args.temperature,'runs_per_scenario':args.runs,'systems':args.systems,
                'implementation_sha256':implementation_hash,'seed_scope':'job ordering and bootstrap only; model sampling is not seeded',
                'seed':args.seed,'scenario_sha256':hashlib.sha256(snapshot_text.encode()).hexdigest(),
                'rubric_version':2,'requested_max_tokens':args.max_tokens,'requested_reasoning_effort':args.reasoning_effort,'retry_policy':'No retries or model fallback; failures are measured.',
                'ablation_scope':'Compliance Officer and host compliance/news gate disabled; Treasury hard limits remain.',
                'warning':'MOCK RESULTS ARE NOT LLM PERFORMANCE EVIDENCE' if args.mock else None}
    (output/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    jobs = [(s,repeat,system) for _,s in scenarios for repeat in range(1,args.runs+1) for system in args.systems]
    random.Random(args.seed).shuffle(jobs)
    records=[]
    with (output/'runs.jsonl').open('w',encoding='utf-8') as stream:
        for index,(scenario,repeat,system) in enumerate(jobs,1):
            result=run_system(scenario,system,client=client)
            result.update(scenario_id=scenario['id'],scenario_version=scenario.get('scenario_version'),repeat=repeat,mock=args.mock)
            stream.write(json.dumps(result,allow_nan=False)+'\n');stream.flush()
            records.append(result)
            print(f"[{index}/{len(jobs)}] {scenario['id']} {system} repeat={repeat}: {result['status']}, correct={result['metrics']['correct']}", flush=True)
    rows=[]
    for r in records:
        rows.append({'scenario_id':r['scenario_id'],'repeat':r['repeat'],'system':r['system'],
                     'status':r['status'],'error':r.get('error'),'action':r.get('decision',{}).get('action'),
                     **{key:value for key,value in r['metrics'].items() if not isinstance(value,(dict,list))}})
    with (output/'metrics.csv').open('w',newline='',encoding='utf-8') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    report=aggregate(records,args.runs,args.seed)
    (output/'summary.json').write_text(json.dumps(report,indent=2,allow_nan=False),encoding='utf-8')
    (output/'report.md').write_text(reflection_markdown(report,args.mock),encoding='utf-8')
    # Blank human-review fields, never fabricated rationale ratings.
    with (output/'manual_review.csv').open('w',newline='',encoding='utf-8') as f:
        writer=csv.writer(f);writer.writerow(['scenario_id','repeat','system','rationale','evidence_use_1_5','tradeoffs_1_5','consistency_1_5','uncertainty_1_5','hallucinated_numbers','injection_adherence_notes','reviewer'])
        for r in records:
            writer.writerow([r['scenario_id'],r['repeat'],r['system'],r.get('decision',{}).get('rationale','')]+['']*7)
    print('Saved:',output)
    return output


if __name__ == '__main__':
    main()
