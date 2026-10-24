"""Isolated, bounded quality/capacity checks. Never truncates a range to fit."""
import argparse
import json
import math
import platform
import random
import resource
import subprocess
import sys
import time
from research.custom_river import RiverGame

GATE_PCT=.5


def scenarios():
    # All live seats have uncertainty, including all five opponents at six seats.
    counts={2:[6,6],3:[4,4,4],4:[4,4,2,2],5:[4,2,2,2,2],6:[2]*6}
    for texture,board in [('dry',['2c','4d','7h','9s','Jc']),('flush',['2s','5s','9s','Kh','Ad'])]:
        for n,widths in counts.items():
            rng=random.Random(20261025+n+100*(texture=='flush'))
            deck=[r+s for r in '23456789TJQKA' for s in 'cdhs' if r+s not in board]
            ranges=[]
            for width in widths:
                hands=[];seen=set()
                while len(hands)<width:
                    pair=tuple(sorted(rng.sample(deck,2)))
                    if pair in seen:continue
                    seen.add(pair);hands.append((''.join(pair),rng.choice([.2,.5,1.,2.])))
                ranges.append(hands)
            yield {'name':f'{texture}_{n}','input':dict(board=board,ranges=ranges,pot=60*n,
                        stacks=[100]*n,initial_contributions=[60]*n,bet_sizes=[40],raise_sizes=[80],max_raises=1,min_bet=10)}
    # Deliberately oversized: test refusal, not an attempted full-range solve.
    yield scenarios_base()


def scenarios_base():
    board=['2c','4d','7h','9s','Jc']
    hands=[('AhAd',1),('KhKd',1),('QhQd',1)]
    return {'name':'rejected_3_power_6','expected_rejection':True,
            'input':dict(board=board,ranges=[hands]*6,pot=360,stacks=[100]*6,
                         initial_contributions=[60]*6,bet_sizes=[40],raise_sizes=[80],max_raises=1,min_bet=10)}


def peak_rss_mib():
    raw=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return raw/(1024*1024 if sys.platform=='darwin' else 1024)


def worker(case,iterations,method='cfr_plus',include_policy=False):
    def progress(phase):print(json.dumps({'phase':phase,'observed_peak_rss_mib':peak_rss_mib()}),flush=True)
    progress('build');start=time.perf_counter()
    try:game=RiverGame(**case['input'])
    except ValueError as error:
        return {'status':'rejected','reason':str(error),'build_seconds':time.perf_counter()-start,'peak_rss_mib':peak_rss_mib()}
    build=time.perf_counter()-start
    progress('train');start=time.perf_counter();policy=game.train(iterations,method=method);train=time.perf_counter()-start
    progress('measure');start=time.perf_counter();metrics=game.measure(policy);measure=time.perf_counter()-start
    exported={'policy':[[key,policy[key]] for key in sorted(policy)]} if include_policy else {}
    return {**exported,'method':method,'status':'completed','build_seconds':build,'train_seconds':train,'measure_seconds':measure,
            'peak_rss_mib':peak_rss_mib(),'public_nodes':len(game.nodes),'joint_deals':len(game.deals),
            'information_sets':len(game.keys),'metrics':metrics,
            'passes_quality_gate':metrics['max_unilateral_gain_pct_pot']<=GATE_PCT}


def decode_lines(output,allow_partial=False):
    if isinstance(output,bytes):output=output.decode()
    lines=[line for line in (output or '').splitlines() if line.strip()];events=[]
    for i,line in enumerate(lines):
        try:events.append(json.loads(line))
        except json.JSONDecodeError:
            if not allow_partial or i!=len(lines)-1:raise
    return events


def run_case(case,iterations,timeout_seconds,method='cfr_plus',include_policy=False):
    command=[sys.executable,'-m','research.benchmark_capacity','--worker','--iterations',str(iterations),'--method',method]
    if include_policy:command.append('--include-policy')
    start=time.perf_counter()
    try:
        completed=subprocess.run(command,input=json.dumps(case),text=True,capture_output=True,timeout=timeout_seconds)
        if completed.returncode:
            return {'status':'error','reason':completed.stderr[-2000:],'wall_seconds':time.perf_counter()-start}
        events=decode_lines(completed.stdout)
        return {**events[-1],'wall_seconds':time.perf_counter()-start}
    except subprocess.TimeoutExpired as error:
        events=[event for event in decode_lines(error.stdout,allow_partial=True) if 'phase' in event]
        return {'status':'timed_out','wall_seconds':time.perf_counter()-start,
                'last_phase':events[-1]['phase'] if events else 'startup',
                'last_observed_peak_rss_mib':events[-1]['observed_peak_rss_mib'] if events else None,
                'note':'No final policy or quality result; observed RSS is a lower bound, not the timed-out process peak.'}


def suite_passes(rows):
    return all((r['status']=='rejected' and '64 raw joint' in r.get('reason',''))
               if r.get('expected_rejection') else (r['status']=='completed' and r['passes_quality_gate']) for r in rows)


def benchmark(iterations=100,timeout_seconds=45,method='cfr_plus'):
    rows=[]
    for case in scenarios():
        print('Starting '+case['name'],file=sys.stderr,flush=True)
        result=run_case(case,iterations,timeout_seconds,method=method)
        rows.append({**case,**result})
        print(case['name']+': '+result['status'],file=sys.stderr,flush=True)
    completed=[r for r in rows if r['status']=='completed']
    return {'method':method,'iterations':iterations,'timeout_seconds_per_case':timeout_seconds,'gate_pct_pot':GATE_PCT,
            'python':sys.version,'platform':platform.platform(),
            'scope':'Fixed public synthetic weighted ranges, one bet size/one capped raise. All seats uncertain. RSS includes interpreter/imports. Timeouts yield no quality claim.',
            'results':rows,'passes_suite':suite_passes(rows),'summary':{'completed':len(completed),'quality_passed':sum(r['passes_quality_gate'] for r in completed),
                'timed_out':sum(r['status']=='timed_out' for r in rows),'rejected':sum(r['status']=='rejected' for r in rows),
                'errors':sum(r['status']=='error' for r in rows)}}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--iterations',type=int,default=100)
    parser.add_argument('--timeout-seconds',type=float,default=45)
    parser.add_argument('--worker',action='store_true')
    parser.add_argument('--method',choices=['cfr_plus','cfr_plus_indexed'],default='cfr_plus')
    parser.add_argument('--include-policy',action='store_true',help='Export policy for numerical equivalence checks')
    parser.add_argument('--check',action='store_true',help='Fail on incomplete/failed quality controls or wrong expected rejection')
    args=parser.parse_args()
    if not 1<=args.iterations<=2000 or not math.isfinite(args.timeout_seconds) or args.timeout_seconds<=0:parser.error('Positive bounded iterations/timeout required.')
    report=worker(json.load(sys.stdin),args.iterations,args.method,args.include_policy) if args.worker else benchmark(args.iterations,args.timeout_seconds,args.method)
    print(json.dumps(report,indent=None if args.worker else 2),flush=True)
    if args.check and not args.worker and not report['passes_suite']:sys.exit(1)
