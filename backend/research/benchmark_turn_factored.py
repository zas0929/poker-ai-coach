"""Reproduce identical public turn games before/after exact factored storage."""
import argparse
import gzip
from hashlib import sha256
import json
from pathlib import Path
import platform
import sys
import time
from research.benchmark_capacity import peak_rss_mib
from research.benchmark_expanded import run_guarded
from research.river_snapshot import digest
from research.turn_snapshot import build_turn_from_snapshot

FIXTURE = Path(__file__).parent/'fixtures/turn-factored-positions-v1.json.gz'
FILES = ('turn_reference.py','turn_snapshot.py','turn_packed.py','build_turn_kernel.py',
         'native/turn_cfr.cpp','turn_native.py','custom_river.py','native_cfr.py',
         'native/cfr.cpp','benchmark_turn_factored.py','benchmark_expanded.py')


def worker(request,iterations,method='factored'):
    def phase(name):
        print(json.dumps({'phase':name,'observed_peak_rss_mib':peak_rss_mib()}),flush=True)
    config=dict(request['input'])
    if method=='factored':
        config.update(utility_storage='factored',max_nodes=30000,max_work=6000000)
    phase('build');start=time.perf_counter()
    try:
        game,metadata=build_turn_from_snapshot(request['snapshot'],request['selected_hands'],**config)
    except ValueError as error:return {'status':'rejected','reason':str(error)}
    build=time.perf_counter()-start;phase('train');start=time.perf_counter()
    try:policy=game.train(iterations,method='cfr_plus_native',max_visits=1000000000 if method=='factored' else 200000000)
    except (ValueError,RuntimeError) as error:return {'status':'rejected','reason':str(error)}
    train=time.perf_counter()-start;phase('measure');start=time.perf_counter()
    try:
        values=game.root_action_values(policy,request['own_hand']);metrics=game.measure(policy)
    except ValueError as error:return {'status':'rejected','reason':str(error)}
    packed=game.packed if method=='factored' else {}
    return {'status':'completed','peak_rss_mib':peak_rss_mib(),'iterations':iterations,
        'build_seconds':build,'train_seconds':train,'measure_seconds':time.perf_counter()-start,
        'public_nodes':len(game.nodes),'outcomes':len(game.outcomes),
        'dense_equivalent_entries':len(game.nodes)*len(game.outcomes),
        **{name:packed.get(name) for name in ('storage_entries','terminal_states','rank_orders',
                                            'training_visits','measurement_visits')},
        'policy_slots':packed.get('slots'),'metrics':metrics,'root_values':values,
        'model':{'configuration':config,'source_information_key':metadata['source_information_key']},
        'scope':'same_full_explicit_subsets_all_rivers_no_truncation'}


def benchmark(iterations=100,seconds=10,memory=128):
    fixture=json.loads(gzip.decompress(FIXTURE.read_bytes()))
    if fixture['version']!=1:raise ValueError('Frozen fixture v1 required.')
    rows=[]
    for request in fixture['requests']:
        players=len(request['snapshot']['players'])
        play={k:v for k,v in request['input'].items() if k.endswith('_sizes') or k.endswith('_raises')}
        key=digest({'snapshot':request['snapshot'],'selected_hands':request['selected_hands'],
                    'own_hand':request['own_hand'],'play':play})
        row={'players':players,'model_key':key}
        for mode in ('reference','factored'):
            print('Starting '+str(players)+' seats '+mode,file=sys.stderr,flush=True)
            row[mode]=run_guarded(request,iterations,seconds,memory,method=mode,
                                  worker_module='research.benchmark_turn_factored')
            print(str(players)+' '+mode+' '+row[mode]['status'],file=sys.stderr,flush=True)
        rows.append(row)
    return {'version':1,'platform':platform.platform(),'iterations':iterations,'wall_seconds':seconds,
        'memory_mib':memory,'fixture_sha256':sha256(FIXTURE.read_bytes()).hexdigest(),
        'sources':{name:sha256((Path(__file__).parent/name).read_bytes()).hexdigest() for name in FILES},
        'scope':'Identical frozen public decisions, weighted explicit two-hand subsets, all compatible rivers, same legal sizes/caps. Only representation and computational guards differ. RSS sampling is a soft limit; local timings are not server guarantees.',
        'results':rows}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker',action='store_true')
    parser.add_argument('--method',choices=('reference','factored'),default='factored')
    parser.add_argument('--iterations',type=int,default=100)
    parser.add_argument('--timeout-seconds',type=float,default=10)
    parser.add_argument('--memory-mib',type=float,default=128)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    if args.worker:print(json.dumps(worker(json.load(sys.stdin),args.iterations,args.method)),flush=True)
    else:
        result=benchmark(args.iterations,args.timeout_seconds,args.memory_mib)
        if args.output:args.output.write_text(json.dumps(result,indent=2)+'\n')
        else:print(json.dumps(result,indent=2))
        if any(row['factored']['status']!='completed' for row in result['results']):sys.exit(1)
