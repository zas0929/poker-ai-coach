"""Explicit local-only launcher. Flags affect this process, never .env/hosting."""
import argparse
import json
import os
from pathlib import Path
from research.trainer_shadow_bridge import plan_configuration
from research.native_cfr import load_library


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=8000)
    parser.add_argument('--plan',type=Path,default=Path(__file__).parent/'config/local-shadow-policy.json')
    args=parser.parse_args(argv)
    if not 1<=args.port<=65535:parser.error('Choose a port from 1 to 65535.')
    try:
        path=args.plan.resolve()
        if path.stat().st_size>1024*1024:raise ValueError('Plan exceeds local size limit.')
        plan_configuration(json.loads(path.read_text()))
        load_library() # explicit prebuilt kernel only; no automatic compilation
    except (OSError,ValueError,TypeError,KeyError,RuntimeError) as error:parser.error(str(error))
    os.environ['POKER_LOCAL_TRAINER_SHADOW']='1'
    os.environ['POKER_LOCAL_TRAINER_SHADOW_PLAN']=str(path)
    import uvicorn
    uvicorn.run('app.main:app',host='127.0.0.1',port=args.port,workers=1)


if __name__=='__main__':main()
