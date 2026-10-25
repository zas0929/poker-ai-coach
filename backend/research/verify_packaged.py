"""Build-time smoke check of the final image; no database, network or auto-build."""
import json
from pathlib import Path
from research.analysis_contract import ResearchLimits
from research.lesson_values import analyze
from research.native_cfr import load_library


def verify():
    load_library()  # ABI, flags, source hash and binary hash must match.
    examples=json.loads((Path(__file__).parent/'fixtures/river-lessons-v1.json').read_text())['examples']
    rows=[]
    for row in examples:
        result=analyze(row['request'],ResearchLimits(iterations=300,wall_seconds=10,memory_mib=128))
        if result['status']!='ready' or not result.get('action_values'):
            codes=[reason['code'] for reason in result['reasons']]
            raise RuntimeError('Packaged river check failed: '+row['id']+' '+str(codes))
        rows.append({'opponents':row['opponents'],'status':result['status'],
                     'quality_pct_pot':result['quality']['value']})
    from research.build_turn_kernel import load_library as load_turn
    from research.turn_analysis import analyze as analyze_turn
    load_turn()
    probe=json.loads((Path(__file__).parent/'fixtures/turn-package-probe-v1.json').read_text())
    turn=analyze_turn(probe,ResearchLimits(iterations=100,wall_seconds=10,memory_mib=128))
    if turn['status']!='ready' or not turn.get('action_values'):
        raise RuntimeError('Packaged turn check failed: '+str(turn['reasons']))
    return {'native_kernel':'verified','isolated_river_models':rows,
            'turn_kernel':'verified','isolated_turn_probe':{
                'status':turn['status'],'quality_pct_pot':turn['quality']['value']}}


if __name__=='__main__':
    print(json.dumps(verify()),flush=True)
