"""Full known-corpus checkpointed reallocation, not independent validation."""
import json
from hashlib import sha256
from pathlib import Path
import sys
from collections import Counter
from research.validate_adaptive_strategy import load_manifest
from research.reallocation_cycle import run_cycle


def summarize(rows):
    eligible=[r for r in rows if r['result']['status']!='unavailable']
    base=lambda r:r['result']['baseline']['checkpoint']['metrics']['max_unilateral_gain_pct_pot']<=.5
    ready=lambda r:r['result']['status']=='ready'
    return {'attempted':len(rows),'baseline_available':len(eligible),
        'baseline_ready':sum(base(r) for r in eligible),'final_ready':sum(ready(r) for r in eligible),
        'new_passes':sum(not base(r) and ready(r) for r in eligible),'lost_passes':sum(base(r) and not ready(r) for r in eligible),
        'statuses':dict(Counter(r['result']['status'] for r in rows)),
        'trial_process_statuses':dict(Counter(t['status'] for r in rows for t in r['result']['attempts']))}


def benchmark():
    path=Path(__file__).parents[2]/'docs/research/adaptive-validation-manifest-2026-10-24.json';plan=load_manifest(path);rows=[]
    for case in plan['cases']:
        print(case['name'],file=sys.stderr,flush=True);result=run_cycle(case)
        # Keep every checkpoint metric/hash, but avoid multiplying full policies in report.
        for container in [result.get('baseline',{}),result,*result['attempts']]:
            for key in ('checkpoint','best_checkpoint'):
                cp=container.get(key)
                if cp is not None:
                    cp=dict(cp);cp['policy_sha256']=sha256(json.dumps(cp.pop('policy'),sort_keys=True).encode()).hexdigest();container[key]=cp
        rows.append({'case':case,'result':result})
    load_manifest(path)
    return {'scope':'46 known regression cases. 45s total cooperative parent budget with externally killed child trials; completed checkpoints retained. Additional at most 4 merge trials/retrains, not equal compute to baseline.',
            'source_sha256':{p:sha256((Path(__file__).parent/p).read_bytes()).hexdigest() for p in ('reallocation_cycle.py','benchmark_reallocation_cycle.py','group_reallocation.py','adaptive_strategy_indexed.py')},
            'summary':summarize(rows),'by_live_players':{str(n):summarize([r for r in rows if r['case']['live_players']==n]) for n in range(2,7)},'results':rows}


if __name__=='__main__':print(json.dumps(benchmark(),indent=2,allow_nan=False))
