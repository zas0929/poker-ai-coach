"""Prespecified correction of two malformed holdout inputs; never replaces base results."""
import argparse
import copy
from hashlib import sha256
import json
from pathlib import Path
import sys
from research.validate_adaptive_strategy import load_manifest,digest,summarize
from research.benchmark_expanded import run_guarded


def plan(base_path):
    base=load_manifest(base_path);cases=[]
    for original in base['cases']:
        if original['family']!='short_raises' or original['dealt_players']!=2:continue
        case=copy.deepcopy(original);case['parent_case_name']=original['name'];case['name']+='_legal_raise'
        case['input']['raise_sizes']=[min(20,max(case['input']['stacks']))]
        cases.append(case)
    payload={'version':1,'parent_manifest_sha256':base['manifest_sha256'],'frozen_source_sha256':base['source_sha256'],
        'supplement_source_sha256':sha256(Path(__file__).read_bytes()).hexdigest(),'cases':cases,
        'iterations_per_round':100,'limits':base['limits'],
        'scope':'Two corrected legal raise inputs, declared separately; original two input errors stay in base results. No algorithm or threshold changes.'}
    return {**payload,'manifest_sha256':digest(payload)}


def write_plan(path,base_path):
    value=plan(base_path)
    if path.exists():
        if json.loads(path.read_text())!=value:raise ValueError('Refusing to overwrite different supplement.')
    else:path.write_text(json.dumps(value,indent=2)+'\n')
    return value


def benchmark(path,base_path):
    value=json.loads(path.read_text())
    if value!=plan(base_path):raise ValueError('Supplement changed or does not match frozen inputs.')
    rows=[]
    for case in value['cases']:
        print(case['name'],file=sys.stderr,flush=True)
        result=run_guarded(case,100,45,128,method='cfr_plus_native',worker_module='research.validate_adaptive_strategy')
        rows.append({'case':case,**result})
    if value!=plan(base_path):raise ValueError('Source/config changed during supplement.')
    return {'manifest_sha256':value['manifest_sha256'],'parent_manifest_sha256':value['parent_manifest_sha256'],
            'scope':value['scope'],'summary':summarize(rows),'results':rows}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--base-manifest',type=Path,required=True)
    p.add_argument('--write-manifest',type=Path);p.add_argument('--manifest',type=Path);args=p.parse_args()
    if args.write_manifest:result={'manifest_sha256':write_plan(args.write_manifest,args.base_manifest)['manifest_sha256']}
    elif args.manifest:result=benchmark(args.manifest,args.base_manifest)
    else:p.error('Write supplement first, then run it.')
    print(json.dumps(result,indent=2,allow_nan=False))
