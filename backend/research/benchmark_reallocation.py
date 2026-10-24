"""Known-case diagnostic of fixed-row-budget merge/reallocation opportunities."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys
from research.custom_river import RiverGame
from research.adaptive_strategy_indexed import train_adaptive_indexed
from research.group_reallocation import audit_reallocation
from research.benchmark_expanded import run_guarded
from research.benchmark_capacity import peak_rss_mib
from research.validate_adaptive_strategy import load_manifest

NAMES=('sizing_2_101','sizing_4_101','sizing_5_211','sizing_6_211','short_raises_4_211','short_raises_6_101',
       'prior_sidepot_4_211','folded_5_211','folded_6_211','board_tie_4_101')


def worker(case):
    def phase(name):print(json.dumps({'phase':name,'observed_peak_rss_mib':peak_rss_mib()}),flush=True)
    phase('build');game=RiverGame(**{**case['input'],'utility_storage':'compact'})
    phase('baseline');policy,e=train_adaptive_indexed(game,max_strategy_rows=len(game.keys)*3//4)
    phase('merge_audit');audit=audit_reallocation(game,policy,e)
    return {'status':'completed','baseline':e,'audit':audit,'peak_rss_mib':peak_rss_mib()}


def benchmark():
    plan=load_manifest(Path(__file__).parents[2]/'docs/research/adaptive-validation-manifest-2026-10-24.json')
    cases={c['name']:c for c in plan['cases']};rows=[]
    for name in NAMES:
        print(name,file=sys.stderr,flush=True);case=cases[name]
        rows.append({'case':case,**run_guarded(case,100,45,128,method='cfr_plus_native',worker_module='research.benchmark_reallocation')})
    return {'scope':'Ten selected known cases; post-hoc diagnostic, not independent validation. Same 75% row budget and 0.5% quality threshold. Additional explicit budget: two merge trials and at most one retrain per trial.',
        'limits':{'wall_seconds':45,'memory_mib':128},'source_sha256':{p:sha256((Path(__file__).parent/p).read_bytes()).hexdigest() for p in ('group_reallocation.py','benchmark_reallocation.py','adaptive_strategy_indexed.py','targeted_strategy.py')},'results':rows}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--worker',action='store_true');p.add_argument('--iterations',type=int,default=100);p.add_argument('--method',default='cfr_plus_native');args=p.parse_args()
    print(json.dumps(worker(json.load(sys.stdin)) if args.worker else benchmark(),indent=None if args.worker else 2,allow_nan=False))
