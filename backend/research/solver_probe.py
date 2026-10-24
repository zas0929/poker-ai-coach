"""Local-only TexasSolver CLI experiment. Never imported by the web application.
No upstream sources/binaries are bundled. Uses synthetic river ranges only.
"""
import argparse
from contextlib import nullcontext
import json
import math
import platform
import random
import re
import resource
import subprocess
import tempfile
import time
from pathlib import Path

from research.river_reference import check_solution

CARD = re.compile(r'^[2-9TJQKA][cdhs]$')

def validate(spec):
    board = spec['board']
    if len(board) != 5 or len(set(board)) != 5 or not all(CARD.fullmatch(c) for c in board):
        raise ValueError('Exactly five distinct river cards required.')
    if any(type(spec[k]) is not int or not 1 <= spec[k] <= 10000 for k in ('pot','stack')):
        raise ValueError('Positive bounded integer pot and remaining effective stack required.')
    legal=[]
    for side in ('oop','ip'):
        combos=spec[side]
        if not 1 <= len(combos) <= 100:
            raise ValueError('Prototype ranges contain 1–100 explicit combos each.')
        seen=set()
        for combo,weight in combos:
            cards=(combo[:2],combo[2:])
            key=frozenset(cards)
            if len(combo)!=4 or not all(CARD.fullmatch(c) for c in cards) or len(key)!=2 or key.intersection(board) or key in seen:
                raise ValueError('Invalid, blocked or duplicate range combo.')
            if not math.isfinite(weight) or not 0 < weight <= 1:
                raise ValueError('Weights must be finite and in (0,1].')
            seen.add(key)
        legal.append(seen)
    if not any(not a.intersection(b) for a in legal[0] for b in legal[1]):
        raise ValueError('Ranges have no disjoint matchup.')

def commands(spec, output):
    validate(spec)
    lines=[f"set_pot {spec['pot']}",f"set_effective_stack {spec['stack']}",'set_board '+','.join(spec['board'])]
    for side in ('oop','ip'):
        lines.append('set_range_'+side+' '+','.join(f'{combo}:{weight}' for combo,weight in spec[side]))
        lines.extend([f'set_bet_sizes {side},river,bet,50',f'set_bet_sizes {side},river,raise,100',f'set_bet_sizes {side},river,allin'])
    # Verify actual exported sizes: upstream's threshold includes already committed money.
    lines.extend(['set_allin_threshold 1','build_tree','set_thread_num 1','set_accuracy 0.1','set_max_iteration 1000','set_print_interval 100','set_use_isomorphism 1','start_solve','set_dump_rounds 2',f'dump_result {output}'])
    return '\n'.join(lines)+'\n'

def summarize(tree):
    nodes=combos=0
    def visit(node):
        nonlocal nodes,combos
        if node.get('node_type')!='action_node': return
        nodes+=1
        actions=node['actions']; strategy=node.get('strategy',{})
        if strategy.get('actions')!=actions: raise ValueError('Action order mismatch.')
        for probabilities in strategy.get('strategy',{}).values():
            if len(probabilities)!=len(actions) or any(not math.isfinite(p) or not 0<=p<=1 for p in probabilities) or abs(sum(probabilities)-1)>1e-5:
                raise ValueError('Invalid strategy probabilities.')
            combos+=1
        for child in node.get('childrens',{}).values(): visit(child)
    visit(tree)
    if not nodes or not combos: raise ValueError('Missing strategy.')
    if 'BET 50.000000' not in tree['actions']: raise ValueError('Requested half-pot size is missing.')
    return {'action_nodes':nodes,'strategy_rows':combos,'root_player':tree['player'],'root_actions':tree['actions'],'ev_per_action_exported':False}

def fixtures():
    board=['2c','4d','7h','9s','Jc']
    rng=random.Random(20261024); deck=[r+s for r in '23456789TJQKA' for s in 'cdhs' if r+s not in board]
    def ranges():
        result={}
        while len(result)<48:
            cards=sorted(rng.sample(deck,2));result[''.join(cards)]=rng.choice([.25,.5,1])
        return list(result.items())
    return [dict(name='known_nuts',board=board,pot=100,stack=100,oop=[('AhAd',1)],ip=[('QhQd',1)]),dict(name='board_tie',board=['As','Ks','Qs','Js','Ts'],pot=100,stack=100,oop=[('2h2d',1)],ip=[('3h3d',1)]),dict(name='weighted_48_vs_48',board=board,pot=100,stack=100,oop=ranges(),ip=ranges())]

def verify_control(spec, tree):
    if spec['name'] not in ('known_nuts','board_tie'): return
    for action in tree['actions']:
        if not action.startswith('BET '): continue
        response=tree['childrens'][action]
        rows=response['strategy']['strategy']
        fold=response['actions'].index('FOLD')
        # On a board-only tie, calling AND raising can be equally good. Folding is not.
        valid=rows and all(p[fold]>=.999 if spec['name']=='known_nuts' else p[fold]<=.001 for p in rows.values())
        if not valid: raise ValueError(f"Analytical control failed: {spec['name']}, {action}: {rows}")


def run(binary, resources, timeout=120, artifacts=None):
    binary=Path(binary).resolve(strict=True); resources=Path(resources).resolve(strict=True)
    if artifacts:
        Path(artifacts).mkdir(parents=True, exist_ok=True)
    with (nullcontext(str(Path(artifacts).resolve())) if artifacts else tempfile.TemporaryDirectory(prefix='poker-solver-')) as directory:
        directory=Path(directory)
        # A fixed relative filename avoids command injection/path whitespace in upstream's DSL.
        specs=fixtures(); text=''.join(commands(spec,f'result-{i}.json') for i,spec in enumerate(specs))
        (directory/'input.txt').write_text(text)
        started=time.perf_counter()
        with (directory/'process.log').open('w') as log:
            subprocess.run([str(binary),'-i','input.txt','-r',str(resources)],cwd=directory,stdout=log,stderr=subprocess.STDOUT,timeout=timeout,check=True)
        elapsed=time.perf_counter()-started
        log=(directory/'process.log').read_text(errors='replace')
        blocks=log.split('<<<START SOLVING>>>')[1:]
        if len(blocks)!=len(specs): raise ValueError('Not all scenarios were solved.')
        results=[]
        for i,(spec,block) in enumerate(zip(specs,blocks)):
            tree=json.loads((directory/f'result-{i}.json').read_text())
            summary=summarize(tree)
            gaps=re.findall(r'Total exploitability ([\d.eE+-]+) precent',block)
            if not gaps or not math.isfinite(float(gaps[-1])) or not 0<=float(gaps[-1])<=.1:
                raise ValueError('Solver did not reach requested reported convergence.')
            verify_control(spec,tree)
            reference=check_solution(spec,tree)
            if reference['independent_exploitability_percent_pot']>.1001:
                raise ValueError('Independent best-response convergence check failed.')
            results.append({'scenario':spec['name'],**summary,**reference,'reported_gap_percent_pot':float(gaps[-1]),'last_reported_solve_seconds':float(re.findall(r'time used: ([\d.eE+-]+)',block)[-1]),'analytical_control':spec['name']!='weighted_48_vs_48'})
        rss=resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
        return {'platform':platform.platform(),'wall_seconds_including_resource_load':round(elapsed,3),'child_peak_rss_mib':round(rss/(1024**2 if platform.system()=='Darwin' else 1024),1),'process_model':'one process, three sequential synthetic river scenarios','results':results,'limitations':'Independent best responses cover only these small river trees and explicit ranges. Not a live hand adapter, full-game solver, or production service.'}

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--binary',required=True);parser.add_argument('--resources',required=True);parser.add_argument('--artifacts',help='Keep synthetic inputs, logs and raw strategies in this local directory');args=parser.parse_args()
    print(json.dumps(run(args.binary,args.resources,artifacts=args.artifacts),indent=2))
