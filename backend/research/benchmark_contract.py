"""Reproducible real-process admission controls, including intentional refusals."""
import copy
import json
import os
from unittest.mock import patch
from research.analysis_contract import ResearchLimits,analyze,recheck_decision
from research.benchmark_midriver_ranges import make_case


def benchmark():
    case=make_case('contract',2,[3,3],20261047)
    request={k:case[k] for k in ('snapshot','selected_hands','input')}
    request['own_hand']=case['selected_hands'][case['snapshot']['actor_id']][0]
    rows=[]
    def check(name,expected,req=request,limits=None,**kwargs):
        result=analyze(req,limits,**kwargs)
        assert result['status']==expected,(name,result)
        assert not result['admission']['live_advice_allowed']
        assert result['fallback']['retain_current_advice']
        assert (result['candidate'] is not None)==(expected=='ready')
        rows.append({'name':name,'expected_status':expected,'result':result})
    check('ready_two_seats','ready')
    obsolete=recheck_decision(rows[-1]['result'],'new-decision')
    assert obsolete['status']=='stale' and obsolete['candidate'] is None
    rows.append({'name':'changed_during_calculation','expected_status':'stale','result':obsolete})
    check('quality_rejected','quality_rejected',limits=ResearchLimits(iterations=1,quality_gate_pct_pot=1e-12))
    check('time_budget','budget_exceeded',limits=ResearchLimits(wall_seconds=.001))
    check('memory_budget','budget_exceeded',limits=ResearchLimits(memory_mib=1))
    check('stale_decision','stale',expected_source_key='obsolete')
    bad=copy.deepcopy(request);bad['snapshot']['players'][0]['cards']=['private']
    check('accidental_hidden_data','invalid_input',req=bad)
    bad=copy.deepcopy(request);bad['snapshot']['street']='turn'
    check('unsupported_street','unsupported',req=bad)
    bad=copy.deepcopy(request);bad['own_hand']='2h3h'
    check('hand_outside_selected_subset','unsupported',req=bad)
    bad=copy.deepcopy(request);bad['snapshot']['pot']+=1
    check('corrupt_public_snapshot','unsupported',req=bad)
    with patch.dict(os.environ,{'POKER_RESEARCH_NATIVE_LIB':'/tmp/poker-contract-intentionally-missing/native.dylib'}):
        check('missing_native_library','unavailable')
    case=make_case('six',6,[3]*6,20261045)
    wide={k:case[k] for k in ('snapshot','selected_hands','input')}
    wide['own_hand']=case['selected_hands'][case['snapshot']['actor_id']][0]
    check('ready_six_seats','ready',req=wide,limits=ResearchLimits(wall_seconds=20))
    return {'scope':'Real-process offline admission controls, never live advice.',
            'summary':{'total':len(rows),'expected_statuses_matched':len(rows)},'results':rows}


if __name__=='__main__':print(json.dumps(benchmark(),indent=2,allow_nan=False))
