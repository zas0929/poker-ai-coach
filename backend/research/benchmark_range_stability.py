"""Multi-seed/width/hand-category controls with common wider reference EVs.
References are finite bounded models, not truth; no trainer policy is changed.
"""
import argparse
import json
from hashlib import sha256
from pathlib import Path
import sys
import time
from research.benchmark_snapshot import control
from research.benchmark_expanded import run_guarded
from research.benchmark_capacity import peak_rss_mib
from research.public_subset_policy import select_public_subset,POLICY_NAME
from research.stratified_subset import select_stratified_subset,NAME,probe_hands
from research.river_snapshot import build_river_from_snapshot
from research.compare_coach import root_action_values,conditional_deals

SEEDS=(17,31,73)
METHODS={'uniform':(POLICY_NAME,select_public_subset),'stratified':(NAME,select_stratified_subset)}


def corpus():
    yield {'name':'dry_2_facing','snapshot':control(2,river_actions=[('check',None),('bet',10)]),'reference_width':32,
           'input':{'bet_sizes':[10],'raise_sizes':[40,80],'max_raises':1}}
    yield {'name':'flush_3_facing','snapshot':control(3,board=['2s','5s','9s','Kh','Ad'],river_actions=[('check',None),('bet',10),('raise',20)]),'reference_width':8,
           'input':{'bet_sizes':[10],'raise_sizes':[40,80],'max_raises':1}}
    yield {'name':'dry_4_checked','snapshot':control(4,river_actions=[('check',None)]),'reference_width':5,
           'input':{'bet_sizes':[40],'raise_sizes':[80],'max_raises':1}}
    yield {'name':'dry_6_facing_capped','snapshot':control(6,river_actions=[('check',None),('bet',10),('raise',20)]),'reference_width':4,
           'input':{'bet_sizes':[10],'raise_sizes':[],'max_raises':0}}


def worker(case,iterations):
    def phase(name):print(json.dumps({'phase':name,'observed_peak_rss_mib':peak_rss_mib()}),flush=True)
    phase('build');start=time.perf_counter()
    try:game,metadata=build_river_from_snapshot(case['snapshot'],case['selected_hands'],**case['input'])
    except ValueError as error:return {'status':'rejected','reason':str(error),'peak_rss_mib':peak_rss_mib()}
    build=time.perf_counter()-start
    try:_,mass=conditional_deals(game,case['own_hand'])
    except ValueError:return {'status':'unsupported_own_hand','reason':'No compatible joint deal for anchored hand.','peak_rss_mib':peak_rss_mib()}
    phase('train');start=time.perf_counter();policy=game.train(iterations,method='cfr_plus_native');train=time.perf_counter()-start
    phase('measure');start=time.perf_counter();metrics=game.measure(policy)
    q,_=root_action_values(game,policy,case['own_hand'],best_response=True)
    return {'status':'completed','metrics':metrics,'passes_quality_gate':metrics['max_unilateral_gain_pct_pot']<=.5,
        'build_seconds':build,'train_seconds':train,'measure_seconds':time.perf_counter()-start,'peak_rss_mib':peak_rss_mib(),
        'metadata':metadata,'public_nodes':len(game.nodes),'joint_deals':len(game.deals),'conditional_mass':mass,
        'actions':game.root.actions,'probabilities':policy[(game.root.actor,case['own_hand'],game.root.history)],'reference_action_ev_chips':q}


def modes(row):return [a for a,p in zip(row['actions'],row['probabilities']) if abs(p-max(row['probabilities']))<1e-8]


def compare(candidate,reference,pot,bb):
    if candidate.get('status')!='completed' or not candidate.get('passes_quality_gate') or reference.get('status')!='completed' or not reference.get('passes_quality_gate'):return None
    if candidate['actions']!=reference['actions']:raise ValueError('Identical action tree required.')
    a=candidate['probabilities'];b=reference['probabilities'];q=reference['reference_action_ev_chips']
    ev=sum(p*v for p,v in zip(a,q));best=max(q)
    def wager(row):
        sizes=[(p,int(action.split()[1])) for action,p in zip(row['actions'],row['probabilities']) if action.startswith(('BET ','RAISE '))]
        mass=sum(p for p,_ in sizes)
        return sum(p*v for p,v in sizes)/mass if mass>1e-8 else None
    ca,rb=wager(candidate),wager(reference)
    return {'tv':.5*sum(abs(x-y) for x,y in zip(a,b)),'same_modes':modes(candidate)==modes(reference),
        'same_action_kinds':sorted({a.split()[0] for a in modes(candidate)})==sorted({a.split()[0] for a in modes(reference)}),
        'candidate_modes':modes(candidate),'reference_modes':modes(reference),
        'candidate_conditional_wager_to':ca,'reference_conditional_wager_to':rb,
        'conditional_size_delta_bb':abs(ca-rb)/bb if ca is not None and rb is not None else None,
        'candidate_ev_in_reference_chips':ev,'reference_best_first_action_ev_chips':best,
        'first_action_loss_chips':max(0.,best-ev),'first_action_loss_bb':max(0.,best-ev)/bb,
        'first_action_loss_pct_pot':max(0.,best-ev)/pot*100}


def run(case,probe,method,width,seed,iterations):
    name,selector=METHODS[method]
    selected,own,evidence=selector(case['snapshot'],probe['hand'],{'name':name,'width':width,'seed':seed,'max_joint_combos':4096})
    request={'snapshot':case['snapshot'],'selected_hands':selected,'own_hand':own,
             'input':{**case['input'],'max_joint_combos':4096,'utility_storage':'compact'}}
    result=run_guarded(request,iterations,45,128,method='cfr_plus_native',worker_module='research.benchmark_range_stability')
    return {'method':method,'width':width,'seed':seed,'selection':evidence,**result}


def summarize(rows):
    result={}
    for method in METHODS:
        for width in (2,3):
            subset=[r for r in rows if r['candidate']['method']==method and r['candidate']['width']==width]
            eligible=[r for r in subset if len(r['comparisons'])==2]
            values=[c for r in eligible for c in r['comparisons'].values()]
            result[method+'_'+str(width)]={'attempted':len(subset),'both_references_usable':len(eligible),
                'candidate_quality_passed':sum(r['candidate'].get('passes_quality_gate',False) and r['candidate']['status']=='completed' for r in subset),
                'reference_comparisons':len(values),'same_mode_count':sum(c['same_modes'] for c in values),
                'mean_tv':sum(c['tv'] for c in values)/len(values) if values else None,
                'mean_loss_bb':sum(c['first_action_loss_bb'] for c in values)/len(values) if values else None,
                'max_loss_bb':max((c['first_action_loss_bb'] for c in values),default=None)}
    return result


def benchmark(iterations=100):
    references=[];rows=[];reference_disagreements=[]
    for case in corpus():
        for probe in probe_hands(case['snapshot']):
            label=case['name']+'/'+probe['label'];print('References '+label,file=sys.stderr,flush=True)
            refs={method:run(case,probe,method,case['reference_width'],900001,iterations) for method in METHODS}
            references.append({'case':case['name'],'probe':probe,'snapshot_key':case['snapshot']['information_key'],
                               'input':case['input'],'references':refs})
            refdiff=compare(refs['uniform'],refs['stratified'],case['snapshot']['pot'],case['snapshot']['big_blind'])
            reference_disagreements.append({'case':case['name'],'probe':probe['label'],'comparison':refdiff})
            for method in METHODS:
                for width in (2,3):
                    for seed in SEEDS:
                        candidate=run(case,probe,method,width,seed,iterations)
                        comparisons={}
                        for refname,reference in refs.items():
                            comparison=compare(candidate,reference,case['snapshot']['pot'],case['snapshot']['big_blind'])
                            if comparison is not None:comparisons[refname]=comparison
                        rows.append({'case':case['name'],'probe':probe['label'],'candidate':candidate,'comparisons':comparisons})
            print('Done '+label,file=sys.stderr,flush=True)
    statuses={s:sum(r['candidate']['status']==s for r in rows) for s in sorted({r['candidate']['status'] for r in rows})}
    return {'iterations':iterations,'seeds':SEEDS,'candidate_widths':[2,3],'limits':{'wall_seconds':45,'memory_mib':128,'quality_gate_pct_pot':.5},
        'source_sha256':{p:sha256((Path(__file__).parent/p).read_bytes()).hexdigest() for p in ('benchmark_range_stability.py','stratified_subset.py','public_subset_policy.py','compare_coach.py')},
        'scope':'12 public decision/own-hand probes, 144 candidate solves and 24 common wider reference solves. Both reference methods are evaluated; none is full-range truth. Six-seat tree caps future raises at zero.',
        'statuses':statuses,'summary':summarize(rows),'references':references,'reference_disagreements':reference_disagreements,'results':rows}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--worker',action='store_true')
    parser.add_argument('--iterations',type=int,default=100);parser.add_argument('--method',choices=['cfr_plus_native'],default='cfr_plus_native')
    args=parser.parse_args()
    if not 1<=args.iterations<=2000:parser.error('1–2000 iterations required.')
    result=worker(json.load(sys.stdin),args.iterations) if args.worker else benchmark(args.iterations)
    print(json.dumps(result,indent=None if args.worker else 2,allow_nan=False),flush=True)
