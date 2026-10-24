"""Expanded exact-enumeration research controls with external time/RSS monitoring.
RSS sampling is a soft process budget, not an OS hard allocation limit.
"""
import argparse
import json
import math
import platform
import random
import subprocess
import sys
import tempfile
import time
from research.benchmark_capacity import decode_lines


def make_case(name,board,widths,seed):
    rng=random.Random(seed)
    deck=[r+s for r in '23456789TJQKA' for s in 'cdhs' if r+s not in board]
    ranges=[]
    for width in widths:
        hands=[];seen=set()
        while len(hands)<width:
            pair=tuple(sorted(rng.sample(deck,2)))
            if pair in seen:continue
            seen.add(pair);hands.append((''.join(pair),rng.choice([.2,.5,1.,2.])))
        ranges.append(hands)
    n=len(widths)
    return {'name':name,'raw_combinations':math.prod(widths),'input':dict(board=board,ranges=ranges,
            pot=60*n,stacks=[100]*n,initial_contributions=[60]*n,bet_sizes=[40],raise_sizes=[80],
            max_raises=1,min_bet=10,max_joint_combos=4096)}


def scenarios():
    widths={2:[12,12],3:[5,5,5],4:[4,4,4,2],5:[3,3,3,2,2],6:[3,2,2,2,2,2]}
    for texture,board in [('dry',['2c','4d','7h','9s','Jc']),('flush',['2s','5s','9s','Kh','Ad'])]:
        for n,sizes in widths.items():
            yield make_case(f'{texture}_{n}',board,sizes,20261026+n+100*(texture=='flush'))
    yield make_case('wide_2_4096',['2c','4d','7h','9s','Jc'],[64,64],20261027)
    yield make_case('wide_3_4096',['2c','4d','7h','9s','Jc'],[16,16,16],20261028)
    yield make_case('six_729',['2c','4d','7h','9s','Jc'],[3]*6,20261029)


def read_rss_mib(pid):
    result=subprocess.run(['ps','-o','rss=','-p',str(pid)],capture_output=True,text=True,timeout=1)
    text=result.stdout.strip()
    if result.returncode and not text:return None # process may have just exited
    return int(text)/1024 if text else None # ps reports RSS in KiB on macOS/Linux


def run_guarded(case,iterations=100,timeout_seconds=45,memory_mib=128,poll_seconds=.2,method='cfr_plus_indexed'):
    if type(iterations) is not int or not 1<=iterations<=2000 or any(type(v) not in (int,float) or not math.isfinite(v) or v<=0 for v in (timeout_seconds,memory_mib,poll_seconds)):
        raise ValueError('Positive finite time, memory, polling and bounded integer iterations required.')
    command=[sys.executable,'-m','research.benchmark_capacity','--worker','--method',method,'--iterations',str(iterations)]
    start=time.perf_counter();sampled_peak=0.;stopped=None;monitor_error=None
    with tempfile.TemporaryFile(mode='w+t') as output,tempfile.TemporaryFile(mode='w+t') as errors:
        process=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=output,stderr=errors,text=True)
        try:
            process.stdin.write(json.dumps(case));process.stdin.close()
            while process.poll() is None:
                if time.perf_counter()-start>=timeout_seconds:stopped='timed_out';break
                try:rss=read_rss_mib(process.pid)
                except (OSError,ValueError,subprocess.TimeoutExpired) as error:
                    stopped='monitor_error';monitor_error=str(error);break
                if rss is not None:
                    sampled_peak=max(sampled_peak,rss)
                    if rss>memory_mib:stopped='memory_exceeded';break
                elif process.poll() is None:
                    stopped='monitor_error';monitor_error='RSS unavailable for a running worker';break
                time.sleep(poll_seconds)
        finally:
            if process.poll() is None:process.kill()
            process.wait()
        output.seek(0);events=decode_lines(output.read(),allow_partial=stopped is not None)
        base={'wall_seconds':time.perf_counter()-start,'sampled_peak_rss_mib':sampled_peak,
              'memory_limit_mib':memory_mib,'rss_poll_seconds':poll_seconds}
        progress=[e for e in events if 'phase' in e]
        if stopped:
            return {**base,'status':stopped,'last_phase':progress[-1]['phase'] if progress else 'startup',
                    'reason':monitor_error or 'External process budget exceeded; no final policy quality claimed.'}
        if process.returncode:
            errors.seek(0)
            return {**base,'status':'error','reason':errors.read()[-2000:]}
        if not events or 'status' not in events[-1]:return {**base,'status':'error','reason':'Missing final worker result'}
        result=events[-1]
        if result.get('peak_rss_mib',0)>memory_mib:
            return {**base,'status':'memory_exceeded','last_phase':'completed',
                    'worker_peak_rss_mib':result['peak_rss_mib'],
                    'reason':'Worker high-water RSS exceeded budget between samples; quality not accepted.'}
        return {**result,**base}


def benchmark(iterations=100,timeout_seconds=45,memory_mib=128,names=None,method='cfr_plus_indexed',utility_storage=None):
    cases=list(scenarios())
    if names is not None:
        if not names or len(set(names))!=len(names) or set(names)-{c['name'] for c in cases}:
            raise ValueError('Select nonempty, distinct known case names.')
        cases=[c for c in cases if c['name'] in names]
    if utility_storage is not None:
        cases=[{**c,'input':{**c['input'],'utility_storage':utility_storage}} for c in cases]
    rows=[]
    for case in cases:
        print('Starting '+case['name'],file=sys.stderr,flush=True)
        result=run_guarded(case,iterations,timeout_seconds,memory_mib,method=method)
        rows.append({**case,**result})
        print(case['name']+': '+result['status']+(' gap='+str(result['metrics']['max_unilateral_gain_pct_pot']) if 'metrics' in result else ''),file=sys.stderr,flush=True)
    completed=[r for r in rows if r['status']=='completed']
    return {'iterations':iterations,'method':method,'timeout_seconds':timeout_seconds,'memory_mib':memory_mib,
            'python':sys.version,'platform':platform.platform(),'selected_cases':[c['name'] for c in cases],'quality_gate_pct_pot':.5,
            'scope':'Fixed synthetic weighted ranges, explicit raw budget 4096; unchanged node/deal budget one million. 0.2s RSS sampling can overshoot; no OS hard memory limit.',
            'results':rows,'summary':{'total':len(rows),'completed':len(completed),
                'quality_passed':sum(r['passes_quality_gate'] for r in completed),
                'statuses':{s:sum(r['status']==s for r in rows) for s in sorted({r['status'] for r in rows})}}}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--iterations',type=int,default=100);parser.add_argument('--timeout-seconds',type=float,default=45)
    parser.add_argument('--memory-mib',type=float,default=128)
    parser.add_argument('--method',choices=['cfr_plus_indexed','cfr_plus_native'],default='cfr_plus_indexed')
    parser.add_argument('--utility-storage',choices=['dict','compact'])
    parser.add_argument('--cases',nargs='+',help='Explicit subset for follow-up measurements')
    args=parser.parse_args()
    if not 1<=args.iterations<=2000 or any(not math.isfinite(v) or v<=0 for v in (args.timeout_seconds,args.memory_mib)):
        parser.error('Positive finite time/memory and 1–2000 iterations required.')
    print(json.dumps(benchmark(args.iterations,args.timeout_seconds,args.memory_mib,args.cases,args.method,args.utility_storage),indent=2))
