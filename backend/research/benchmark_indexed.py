"""Paired isolated reference/indexed CFR+ comparison on identical fixed games."""
import argparse
import json
import platform
import sys
from research.benchmark_capacity import scenarios,run_case


POLICY_TOLERANCE=1e-10
METRIC_TOLERANCE=1e-8


def compare(reference,indexed):
    if reference['status']!='completed' or indexed['status']!='completed':
        return {'equivalent':False,'reason':'Both methods must finish before comparison.'}
    left=reference['policy'];right=indexed['policy']
    if len(left)!=len(right) or any(a[0]!=b[0] or len(a[1])!=len(b[1]) for a,b in zip(left,right)):
        return {'equivalent':False,'reason':'Information sets/action shapes differ.'}
    policy_error=max((abs(a-b) for (_,ra),(_,rb) in zip(left,right) for a,b in zip(ra,rb)),default=0.)
    metric_error=max(abs(a-b) for key in ('policy_payoffs','best_response_payoffs','unilateral_gains')
                     for a,b in zip(reference['metrics'][key],indexed['metrics'][key]))
    return {'equivalent':policy_error<=POLICY_TOLERANCE and metric_error<=METRIC_TOLERANCE,
            'max_policy_absolute_error':policy_error,'max_payoff_absolute_error':metric_error,
            'training_speedup':reference['train_seconds']/indexed['train_seconds'],
            'wall_speedup':reference['wall_seconds']/indexed['wall_seconds']}


def benchmark(iterations=100,timeout_seconds=45):
    rows=[]
    for number,case in enumerate(c for c in scenarios() if not c.get('expected_rejection')):
        order=['cfr_plus','cfr_plus_indexed'] if number%2==0 else ['cfr_plus_indexed','cfr_plus']
        results={}
        for method in order:
            print(case['name']+' '+method,file=sys.stderr,flush=True)
            results[method]=run_case(case,iterations,timeout_seconds,method=method,include_policy=True)
        comparison=compare(results['cfr_plus'],results['cfr_plus_indexed'])
        for result in results.values():result.pop('policy',None)
        rows.append({**case,'execution_order':order,'methods':results,'comparison':comparison})
        print(case['name']+': '+str(comparison),file=sys.stderr,flush=True)
    return {'iterations':iterations,'timeout_seconds_per_process':timeout_seconds,
            'policy_tolerance':POLICY_TOLERANCE,'payoff_tolerance_chips':METRIC_TOLERANCE,
            'python':sys.version,'platform':platform.platform(),
            'scope':'One paired sequential run per fixed case, fresh process per method, alternating order. Indexed compilation included in training. No sampling or game abstraction changes.',
            'results':rows,'passes_equivalence':all(r['comparison']['equivalent'] for r in rows),
            'passes_quality':all(v['status']=='completed' and v['passes_quality_gate'] for r in rows for v in r['methods'].values())}


if __name__=='__main__':
    import math
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--iterations',type=int,default=100)
    parser.add_argument('--timeout-seconds',type=float,default=45);parser.add_argument('--check',action='store_true')
    args=parser.parse_args()
    if not 1<=args.iterations<=2000 or not math.isfinite(args.timeout_seconds) or args.timeout_seconds<=0:parser.error('Positive bounded iterations/timeout required.')
    report=benchmark(args.iterations,args.timeout_seconds);print(json.dumps(report,indent=2))
    if args.check and not (report['passes_equivalence'] and report['passes_quality']):sys.exit(1)
