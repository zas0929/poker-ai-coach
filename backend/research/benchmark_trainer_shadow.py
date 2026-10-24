"""Local trainer hook -> public preparation -> real native queue -> diagnostics."""
import argparse
import json
import os
from pathlib import Path
import tempfile
import time
from unittest.mock import patch
from hashlib import sha256
from app.api import hand
from app.models.poker import ActionType,PlayerActionRequest
from app.services import trainer_shadow
from app.services.decision_engine import DecisionEngine
from app.services.solver_snapshot import prepare_solver_snapshot,card_text
from research.river_reference import cards
from research.river_snapshot import combo_key
import research.trainer_shadow_bridge as bridge_module


def controlled_hand():
    engine=hand.PokerEngine();state=engine.start_hand(player_count=2)
    state.players[0].cards=cards('AhAd');state.players[1].cards=cards('KhKd')
    board='2c4d7h9sJc';used={'Ah','Ad','Kh','Kd',*[board[i:i+2] for i in range(0,10,2)]}
    state._deck=[c for c in engine._create_deck() if card_text(c) not in used]+list(reversed(cards(board)))
    while state.street.value!='river':
        if state.current_player_id is None:engine.advance(state)
        else:engine.apply_action(state,state.current_player_id,ActionType.CALL if state.betting.call_amount else ActionType.CHECK)
    engine.apply_action(state,state.current_player_id,ActionType.CHECK)
    return state


def wait_for(predicate):
    deadline=time.monotonic()+20
    while time.monotonic()<deadline:
        value=predicate()
        if value:return value
        time.sleep(.01)
    raise AssertionError('Local trainer shadow control did not complete')


def benchmark(plan_override=None):
    state=controlled_hand();snapshot=prepare_solver_snapshot(state);baseline=DecisionEngine().analyze(state)
    picks={'hero':['AhAd','3h3d'],'villain':['KhKd','5h5d']}
    selected={p['id']:[next(row['cards'] for row in p['range'] if combo_key(row['cards'])==combo_key(t)) for t in picks[p['id']]] for p in snapshot['players']}
    plan={'version':1,'decisions':{snapshot['information_key']:{'selected_hands':selected,
          'input':{'bet_sizes':[baseline.recommended_amount,40],'raise_sizes':[80],'max_raises':1,'utility_storage':'compact'}}}}
    if plan_override is not None:plan=plan_override
    previous=hand.current_state;token=hand.training_owner.set(None)
    assert trainer_shadow._bridge is None
    try:
        hand.current_state=state
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'plan.json';path.write_text(json.dumps(plan))
            with patch.dict(os.environ,{'POKER_LOCAL_TRAINER_SHADOW':'1','POKER_LOCAL_TRAINER_SHADOW_PLAN':str(path)}):
                assert trainer_shadow.start_local_shadow()
                # Uses the actual route function and actual current coach; response is unchanged.
                start=time.perf_counter();answer=hand.analyze_hand();hint_seconds=time.perf_counter()-start
                assert answer.model_dump()==baseline.model_dump()
                comparison=wait_for(lambda:next((e for e in trainer_shadow.local_diagnostics()['events'] if e['event']=='comparison'),None))
                assert comparison['represented_exactly'] and not comparison['live_advice_allowed']
                before=trainer_shadow.local_diagnostics()
                hand.apply_action(PlayerActionRequest(action=ActionType.CHECK))
                after=trainer_shadow.local_diagnostics()
                assert after['events'][-1]['event']=='observed'
                assert all(e.get('live_advice_allowed') is not True for e in after['events'])
                executor=trainer_shadow._bridge.executor
                trainer_shadow.stop_local_shadow()
                assert executor.stats()['jobs']==0 and executor.stats()['closed']
        return {'scope':'Local opt-in trainer integration, exact controlled plan; existing hint unchanged. No HTTP deployment.',
            'plan_version':plan['version'],'bridge_source_sha256':sha256(Path(bridge_module.__file__).read_bytes()).hexdigest(),
            'source_information_key':snapshot['information_key'],'selected_public_hands':selected,
            'baseline_action':comparison['baseline_action'],'hint_route_seconds':hint_seconds,
            'comparison':comparison,'before_action':before,'after_action':after,
            'shutdown':executor.stats(),'controls':{'same_hint':True,'exact_plan':True,'native_comparison':True,'state_change_observed':True,'clean_shutdown':True}}
    finally:
        trainer_shadow.stop_local_shadow();hand.current_state=previous;hand.training_owner.reset(token)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--policy-plan',type=Path)
    args=parser.parse_args()
    override=json.loads(args.policy_plan.read_text()) if args.policy_plan else None
    print(json.dumps(benchmark(override),indent=2,allow_nan=False))
