"""Separate cProfile run; timings must not be compared to unprofiled benchmark."""
import argparse
import cProfile
import json
from pathlib import Path
import pstats
from research.benchmark_capacity import scenarios
from research.custom_river import RiverGame


def profile(name='dry_4',iterations=10):
    case=next(c for c in scenarios() if c['name']==name)
    game=RiverGame(**case['input']);profiler=cProfile.Profile()
    profiler.enable();game.train(iterations,method='cfr_plus');profiler.disable()
    stats=pstats.Stats(profiler)
    rows=[{'file':Path(file).name,'line':line,'function':function,'primitive_calls':cc,'calls':nc,
           'self_seconds':tt,'cumulative_seconds':ct} for (file,line,function),(cc,nc,tt,ct,_) in stats.stats.items()]
    return {'scenario':name,'iterations':iterations,'public_nodes':len(game.nodes),'joint_deals':len(game.deals),
            'profiled_seconds':stats.total_tt,'top_self_time':sorted(rows,key=lambda r:r['self_seconds'],reverse=True)[:15],
            'scope':'Training only under cProfile overhead; cumulative times overlap. No native/sampling implementation benchmarked.'}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--case',default='dry_4');parser.add_argument('--iterations',type=int,default=10)
    args=parser.parse_args();print(json.dumps(profile(args.case,args.iterations),indent=2))
