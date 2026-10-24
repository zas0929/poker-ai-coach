"""Paired indexed Python/dict and native/compact comparison, identical game model."""
import argparse
import json
from pathlib import Path
import sys
from research.benchmark_capacity import scenarios,run_case
from research.benchmark_indexed import compare
from research.build_native import default_library
from research.native_cfr import load_library


def benchmark(iterations=100,timeout_seconds=45):
    library=load_library() # explicit prior build required; never compiles in a worker
    path=Path(library._name)
    manifest=json.loads(path.with_suffix(path.suffix+'.json').read_text())
    rows=[]
    for number,case in enumerate(c for c in scenarios() if not c.get('expected_rejection')):
        order=['cfr_plus_indexed','cfr_plus_native'] if number%2==0 else ['cfr_plus_native','cfr_plus_indexed']
        results={}
        for method in order:
            storage='compact' if method=='cfr_plus_native' else 'dict'
            job={**case,'input':{**case['input'],'utility_storage':storage}}
            print(case['name']+' '+method,file=sys.stderr,flush=True)
            results[method]=run_case(job,iterations,timeout_seconds,method=method,include_policy=True)
        comparison=compare(results['cfr_plus_indexed'],results['cfr_plus_native'])
        for result in results.values():result.pop('policy',None)
        rows.append({**case,'execution_order':order,'storage':{'cfr_plus_indexed':'dict','cfr_plus_native':'compact'},'methods':results,'comparison':comparison})
        print(case['name']+': '+str(comparison),file=sys.stderr,flush=True)
    return {'iterations':iterations,'timeout_seconds_per_process':timeout_seconds,
            'native_build':{k:v for k,v in manifest.items() if k!='library'},
            'scope':'One paired sequential run per fixed case; new process per method. Compilation excluded, numeric packing included in train time. Python dict vs native compact payoffs.',
            'results':rows,'passes_equivalence':all(r['comparison']['equivalent'] for r in rows),
            'passes_quality':all(v['status']=='completed' and v['passes_quality_gate'] for r in rows for v in r['methods'].values())}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--iterations',type=int,default=100)
    parser.add_argument('--timeout-seconds',type=float,default=45);parser.add_argument('--check',action='store_true')
    args=parser.parse_args();report=benchmark(args.iterations,args.timeout_seconds);print(json.dumps(report,indent=2))
    if args.check and not (report['passes_equivalence'] and report['passes_quality']):sys.exit(1)
