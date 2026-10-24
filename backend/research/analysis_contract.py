"""Versioned offline admission contract. No live API, advice override or auto-build.
Time/RSS enforced by isolated runner plus final admission checks; RSS is a soft limit.
"""
import argparse
import copy
from dataclasses import asdict,dataclass
from hashlib import sha256
import json
import math
import re
from pathlib import Path
import sys
import time
from research.benchmark_expanded import run_guarded
from research.benchmark_capacity import peak_rss_mib
from research.river_snapshot import build_river_from_snapshot,digest,combo_key

CONTRACT_VERSION=1
ENGINE_VERSION='bounded_river_cfr_plus_v1'
RANGE_VERSION='public_action_heuristic_v1'
FILES=('analysis_contract.py','custom_river.py','river_replay.py','river_snapshot.py',
       'compact_utilities.py','native_cfr.py','native/cfr.cpp','build_native.py','benchmark_expanded.py',
       '../app/services/hand_evaluator.py','../app/services/solver_snapshot.py')
SNAPSHOT_FIELDS={'schema_version','street','board','pot','small_blind','big_blind','button_id','actor_id',
    'dealt_player_count','live_player_count','postflop_order','players','history','range_model','assumptions','information_key'}
PLAYER_FIELDS={'id','seat','position','status','stack','street_committed','total_committed','range'}
TREE_FIELDS={'bet_sizes','raise_sizes','max_raises','max_nodes','max_joint_combos','utility_storage'}


@dataclass(frozen=True)
class ResearchLimits:
    iterations:int=100
    wall_seconds:float=10.
    memory_mib:float=128.
    quality_gate_pct_pot:float=.5

    def __post_init__(self):
        if type(self.iterations) is not int or not 1<=self.iterations<=2000:
            raise ValueError('1–2000 integer iterations required.')
        for name in ('wall_seconds','memory_mib','quality_gate_pct_pot'):
            value=getattr(self,name)
            if not finite_number(value) or value<=0:
                raise ValueError('Positive finite research limits required.')
        if self.quality_gate_pct_pot>.5:raise ValueError('Quality gate cannot exceed 0.5% of decision pot.')


def provenance():
    root=Path(__file__).parent
    return {'engine_version':ENGINE_VERSION,'engine_source_sha256':digest({p:sha256((root/p).read_bytes()).hexdigest() for p in FILES}),
            'range_version':RANGE_VERSION,'range_source_sha256':sha256((root/'../app/services/range_service.py').read_bytes()).hexdigest(),'method':'cfr_plus_native','utility_storage':'compact'}


def finite_number(value):
    try:return type(value) in (int,float) and math.isfinite(value)
    except OverflowError:return False


def validate_request(request):
    """Strict public envelope; never copies accidental hidden data to results."""
    if type(request) is not dict or set(request)!={'snapshot','selected_hands','own_hand','input'}:
        raise ValueError('Expected snapshot, selected_hands, own_hand and input only.')
    snapshot=request['snapshot']
    if type(snapshot) is not dict or set(snapshot)!=SNAPSHOT_FIELDS:
        raise ValueError('Only the exact public schema-v1 snapshot envelope is accepted.')
    if type(snapshot['players']) is not list or any(type(p) is not dict or set(p)-PLAYER_FIELDS for p in snapshot['players']):
        raise ValueError('Only public player fields are accepted; no holdings or names.')
    for player in snapshot['players']:
        if 'range' in player:
            if type(player['range']) is not list or any(type(row) is not dict or set(row)!={'cards','weight'} for row in player['range']):
                raise ValueError('Public ranges contain cards and weight only.')
    if type(snapshot['history']) is not list or any(type(a) is not dict or set(a)!={'player_id','action','amount_added','street'} for a in snapshot['history']):
        raise ValueError('Only public action fields are accepted.')
    if type(request['input']) is not dict or set(request['input'])-TREE_FIELDS:
        raise ValueError('Unknown tree configuration field.')
    if request['input'].get('utility_storage','compact')!='compact':raise ValueError('Contract requires compact payoffs.')
    if type(request['selected_hands']) is not dict or any(type(k) is not str for k in request['selected_hands']) or any(type(v) is not list for v in request['selected_hands'].values()):
        raise ValueError('Explicit public range subsets required.')
    combo_key(request['own_hand'])
    # Reject non-JSON values/NaN before dispatch or identity generation.
    json.dumps(request,allow_nan=False)


def finish(result,status,code,message,stage,candidate=None):
    result.update(status=status,reasons=[] if code is None else [{'code':code,'stage':stage,'message':message}],candidate=candidate)
    result['admission']={'offline_analysis_allowed':status=='ready','live_advice_allowed':False}
    result['fallback']={'source':'current_coach','retain_current_advice':True,
                        'reason':'Research-only contract; live advice is never replaced.'}
    return result


def analyze(request,limits=None,*,expected_source_key=None,cancel_event=None):
    """Only ready yields an offline candidate; all other paths retain coach advice.
    expected_source_key lets a future caller reject a result for an obsolete decision.
    """
    limits=ResearchLimits() if limits is None else limits
    if not isinstance(limits,ResearchLimits):raise ValueError('ResearchLimits required.')
    result={'contract_version':CONTRACT_VERSION,'scope':'offline_bounded_river',
            'provenance':provenance(),'request_key':None,'source_information_key':None,'task_key':None,
            'limits':asdict(limits),'timing':None,'quality':None,'model':None}
    try:validate_request(request)
    except (ValueError,TypeError,KeyError) as error:
        return finish(result,'invalid_input','INVALID_PUBLIC_REQUEST',str(error),'preflight')
    snapshot=request['snapshot'];result['request_key']=digest(request)
    result['source_information_key']=snapshot['information_key']
    if expected_source_key is not None and expected_source_key!=snapshot['information_key']:
        return finish(result,'stale','STALE_DECISION','Requested decision no longer matches the caller.','preflight')
    if snapshot['schema_version']!=1 or snapshot['street']!='river' or snapshot['range_model']!=RANGE_VERSION or not 2<=len(snapshot['players'])<=6:
        return finish(result,'unsupported','UNSUPPORTED_MODEL','Only schema-v1 river, 2–6 original seats and the public heuristic v1 range model are supported.','preflight')
    if cancel_event is not None and cancel_event.is_set():
        return finish(result,'cancelled','ANALYSIS_CANCELLED','Cancelled before process launch.','preflight')
    runner_options={'cancel_event':cancel_event} if cancel_event is not None else {}
    try:
        raw=run_guarded(request,limits.iterations,limits.wall_seconds,limits.memory_mib,
                        method='cfr_plus_native',worker_module='research.analysis_contract',**runner_options)
    except (OSError,ValueError,TypeError):
        return finish(result,'error','RUNNER_FAILED','Isolated runner could not produce a verifiable result.','worker')
    if type(raw) is not dict:
        return finish(result,'error','WORKER_FAILED','Worker returned an invalid result envelope.','worker')
    result['timing']={key:(raw.get(key) if finite_number(raw.get(key)) else None) for key in ('wall_seconds','sampled_peak_rss_mib','rss_poll_seconds','peak_rss_mib','build_seconds','train_seconds','measure_seconds')}
    result['timing']['last_phase']=raw.get('last_phase') if raw.get('last_phase') in ('startup','build','train','measure','completed') else None
    status=raw.get('status')
    failures={'cancelled':('cancelled','ANALYSIS_CANCELLED'),'timed_out':('budget_exceeded','TIME_BUDGET_EXCEEDED'),
              'memory_exceeded':('budget_exceeded','MEMORY_BUDGET_EXCEEDED'),
              'monitor_error':('error','RESOURCE_MONITOR_FAILED'),
              'rejected':('unsupported','UNSUPPORTED_STATE_OR_TREE'),
              'provider_unavailable':('unavailable','NATIVE_KERNEL_UNAVAILABLE'),
              'invalid_probe':('unsupported','UNSUPPORTED_OWN_HAND')}
    if status in failures:
        target,code=failures[status]
        return finish(result,target,code,raw.get('reason','Research calculation was not admitted.'),raw.get('last_phase','worker'))
    if status!='completed':return finish(result,'error','WORKER_FAILED','Worker did not complete a verifiable result.','worker')
    try:json.dumps(raw,allow_nan=False)
    except (ValueError,TypeError):
        return finish(result,'error','INVALID_WORKER_EVIDENCE','Worker evidence must be finite JSON data.','admission')
    # The monitor may observe process exit between polls. Check final elapsed/high-water values too.
    wall=raw.get('wall_seconds');peak=raw.get('peak_rss_mib');sampled=raw.get('sampled_peak_rss_mib')
    if any(not finite_number(v) or v<0 for v in (wall,peak,sampled)):
        return finish(result,'error','MISSING_RESOURCE_EVIDENCE','Finite final timing and memory evidence required.','admission')
    if wall>limits.wall_seconds:return finish(result,'budget_exceeded','TIME_BUDGET_EXCEEDED','Completed after the time budget.','admission')
    if max(peak,sampled)>limits.memory_mib:return finish(result,'budget_exceeded','MEMORY_BUDGET_EXCEEDED','Completed above the memory budget.','admission')
    evidence=raw.get('provenance');metadata=raw.get('metadata',{})
    if type(metadata) is not dict:return finish(result,'error','RESULT_IDENTITY_MISMATCH','Public metadata missing.','admission')
    if evidence!=result['provenance'] or metadata.get('source_information_key')!=snapshot['information_key'] or raw.get('request_key')!=result['request_key'] or raw.get('iterations')!=limits.iterations:
        return finish(result,'error','RESULT_IDENTITY_MISMATCH','Engine, request, decision or iteration identity does not match.','admission')
    if not valid_tree(raw.get('tree'),request):
        return finish(result,'error','INVALID_TREE_EVIDENCE','Explicit matching tree sizes, limits and resource counts required.','admission')
    result['task_key']=metadata.get('task_key');result['model']={**metadata,'tree':raw.get('tree')}
    metrics=raw.get('metrics',{});gap=metrics.get('max_unilateral_gain_pct_pot') if type(metrics) is dict else None
    if not valid_quality(metrics,len(snapshot['players']),snapshot['pot']) or type(result['task_key']) is not str or not re.fullmatch('[0-9a-f]{64}',result['task_key']):
        return finish(result,'error','INVALID_QUALITY_EVIDENCE','Finite nonnegative measured quality and task identity required.','admission')
    result['quality']={'metric':'max_unilateral_gain_pct_decision_pot','value':gap,
        'gate':limits.quality_gate_pct_pot,'passed':gap<=limits.quality_gate_pct_pot,'evidence':metrics,
        'interpretation':'Exact best response in this bounded game; not full-range GTO or calibrated range accuracy.'}
    if gap>limits.quality_gate_pct_pot:return finish(result,'quality_rejected','QUALITY_GATE_FAILED','Bounded strategy did not pass the requested quality gate.','admission')
    candidate=raw.get('candidate')
    if not valid_candidate(candidate,request):
        return finish(result,'error','INVALID_CANDIDATE','Complete finite normalized strategy for the requested own hand and actor required.','admission')
    if cancel_event is not None and cancel_event.is_set():
        return finish(result,'cancelled','ANALYSIS_CANCELLED','Cancelled before result admission.','admission')
    return finish(result,'ready',None,None,'admission',candidate)


def recheck_decision(result,current_source_key):
    """After asynchronous work, discard an obsolete candidate; never promote a refusal."""
    checked=copy.deepcopy(result)
    if checked['source_information_key']!=current_source_key:
        return finish(checked,'stale','STALE_DECISION','Decision changed after calculation; discard the candidate.','delivery')
    return checked


def valid_tree(tree,request):
    if type(tree) is not dict:return False
    config=request['input']
    try:
        for name,default in (('bet_sizes',[50]),('raise_sizes',[])):
            values=tree.get(name)
            if type(values) is not list or values!=sorted(config.get(name,default)):return False
            if len(values)>4 or len(set(values))!=len(values) or any(type(v) is not int or not 1<=v<=10000 for v in values):return False
        if not tree['bet_sizes']:return False
        for name,default,low,high in (('max_nodes',20000,1,20000),('max_joint_combos',64,1,4096)):
            if type(tree.get(name)) is not int or tree[name]!=config.get(name,default) or not low<=tree[name]<=high:return False
        if type(tree.get('future_raise_cap')) is not int or tree['future_raise_cap']!=config.get('max_raises',0) or not 0<=tree['future_raise_cap']<=3:return False
        if tree.get('min_bet')!=request['snapshot']['big_blind']:return False
        nodes=tree.get('public_nodes');deals=tree.get('joint_deals')
        raw=math.prod(len(v) for v in request['selected_hands'].values())
        return (type(nodes) is int and type(deals) is int and 1<=nodes<=tree['max_nodes'] and
                1<=deals<=raw<=tree['max_joint_combos'] and nodes*deals<=1000000)
    except (TypeError,KeyError):return False


def valid_quality(metrics,n,pot):
    if type(metrics) is not dict or not finite_number(pot) or pot<=0:return False
    names=('policy_payoffs','best_response_payoffs','unilateral_gains')
    if any(type(metrics.get(k)) is not list or len(metrics[k])!=n or any(not finite_number(v) for v in metrics[k]) for k in names):return False
    if any(v<0 for v in metrics['unilateral_gains']):return False
    if any(abs(max(0.,b-v)-g)>1e-7 for v,b,g in zip(*(metrics[k] for k in names))):return False
    gap=metrics.get('max_unilateral_gain_pct_pot');conv=metrics.get('nash_conv_chips')
    return (finite_number(gap) and gap>=0 and finite_number(conv) and conv>=0 and
            abs(conv-sum(metrics['unilateral_gains']))<1e-7 and
            abs(gap-max(metrics['unilateral_gains'])/pot*100)<1e-7 and
            abs(sum(metrics['policy_payoffs']))<1e-7)


def valid_candidate(candidate,request):
    if type(candidate) is not dict or set(candidate)!={'actor_id','own_hand','actions','probabilities','compatible_deals','conditional_mass'}:return False
    if candidate['actor_id']!=request['snapshot']['actor_id'] or candidate['own_hand']!=request['own_hand']:return False
    actions=candidate['actions'];probabilities=candidate['probabilities']
    if type(actions) is not list or not actions or any(type(a) is not str or not re.fullmatch(r'(?:FOLD|CHECK|CALL|(?:BET|RAISE) [1-9][0-9]*)',a) for a in actions) or len(set(actions))!=len(actions):return False
    try:
        if actions!=expected_root_actions(request):return False
        if combo_key(request['own_hand']) not in [combo_key(t) for t in request['selected_hands'][candidate['actor_id']]]:return False
    except (ValueError,TypeError,KeyError,IndexError):return False
    if type(probabilities) is not list or len(probabilities)!=len(actions) or any(not finite_number(p) or not 0<=p<=1 for p in probabilities) or abs(sum(probabilities)-1)>1e-8:return False
    return (type(candidate['compatible_deals']) is int and candidate['compatible_deals']>0 and
            finite_number(candidate['conditional_mass']) and 0<candidate['conditional_mass']<=1+1e-8)


def expected_root_actions(request):
    """Verify root action labels from replay without rebuilding the future tree."""
    from research.river_replay import replay_river
    snapshot=request['snapshot'];players=snapshot['players'];ids=[p['id'] for p in players]
    stacks=tuple(p['stack']+p['street_committed'] for p in players)
    folded=tuple(i for i,p in enumerate(players) if p['status']=='folded')
    observed=[(ids.index(a['player_id']),a['action'],a['amount_added']) for a in snapshot['history'] if a['street']=='river']
    cursor=replay_river(stacks,ids.index(snapshot['button_id']),snapshot['big_blind'],folded,observed)
    if not cursor.pending or ids[cursor.pending[0]]!=snapshot['actor_id']:return []
    actor=cursor.pending[0];current=cursor.current
    actions=['FOLD','CALL'] if current>cursor.invested[actor] else ['CHECK']
    funded=tuple(p for p in cursor.alive if cursor.invested[p]<stacks[p])
    reopened=cursor.acted[actor] is None or current-cursor.acted[actor]>=cursor.increment
    config=request['input']
    targets=config.get('bet_sizes',[50]) if current==0 else (config.get('raise_sizes',[]) if config.get('max_raises',0)>0 and reopened else [])
    if len(funded)<2:targets=[]
    minimum=cursor.increment if current==0 else current+cursor.increment
    for total in sorted({min(v,stacks[actor]) for v in targets}):
        if total<=current or (total<minimum and total!=stacks[actor]):continue
        actions.append(('BET ' if current==0 else 'RAISE ')+str(total))
    return actions


def worker(request,iterations):
    def progress(phase):print(json.dumps({'phase':phase,'observed_peak_rss_mib':peak_rss_mib()}),flush=True)
    try:validate_request(request)
    except (ValueError,TypeError,KeyError) as error:return {'status':'rejected','reason':str(error)}
    progress('build');start=time.perf_counter()
    try:game,metadata=build_river_from_snapshot(request['snapshot'],request['selected_hands'],**{**request['input'],'utility_storage':'compact'})
    except ValueError as error:return {'status':'rejected','reason':str(error)}
    build=time.perf_counter()-start;hand=request['own_hand'];actor=game.root.actor
    deals=[(d,w) for d,(texts,w,_) in enumerate(game.deals) if texts[actor]==hand]
    if not deals:return {'status':'invalid_probe','reason':'Own hand must be an exact supported public-subset combo at the current actor.'}
    progress('train');start=time.perf_counter()
    try:policy=game.train(iterations,method='cfr_plus_native')
    except (RuntimeError,OSError):return {'status':'provider_unavailable','reason':'Explicit native build is absent, stale or unavailable; run research/build_native.py.'}
    train=time.perf_counter()-start
    progress('measure');start=time.perf_counter();metrics=game.measure(policy);measure=time.perf_counter()-start
    return {'status':'completed','iterations':iterations,'provenance':provenance(),'request_key':digest(request),
        'metadata':metadata,'tree':{'bet_sizes':list(game.bet_sizes),'raise_sizes':list(game.raise_sizes),
            'future_raise_cap':game.max_raises,'min_bet':game.min_bet,'max_nodes':request['input'].get('max_nodes',20000),
            'public_nodes':len(game.nodes),'joint_deals':len(game.deals),'max_joint_combos':game.max_joint_combos},'metrics':metrics,'build_seconds':build,'train_seconds':train,'measure_seconds':measure,
        'peak_rss_mib':peak_rss_mib(),'candidate':{'actor_id':request['snapshot']['actor_id'],'own_hand':hand,
            'actions':list(game.root.actions),'probabilities':policy[(actor,hand,game.root.history)],
            'compatible_deals':len(deals),'conditional_mass':sum(w for _,w in deals)}}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('request_json',nargs='?',type=Path)
    parser.add_argument('--worker',action='store_true');parser.add_argument('--iterations',type=int,default=100)
    parser.add_argument('--method',choices=['cfr_plus_native'],default='cfr_plus_native')
    parser.add_argument('--wall-seconds',type=float,default=10);parser.add_argument('--memory-mib',type=float,default=128)
    parser.add_argument('--quality-gate',type=float,default=.5);args=parser.parse_args()
    if args.worker:output=worker(json.load(sys.stdin),args.iterations)
    else:
        if args.request_json is None:parser.error('Pass a saved public research request JSON.')
        try:limits=ResearchLimits(args.iterations,args.wall_seconds,args.memory_mib,args.quality_gate)
        except ValueError as error:parser.error(str(error))
        output=analyze(json.loads(args.request_json.read_text()),limits)
    print(json.dumps(output,indent=None if args.worker else 2),flush=True)
