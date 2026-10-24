"""Disabled-by-default local research hooks. No research/native import while disabled."""
import json
import logging
import os
from pathlib import Path

logger=logging.getLogger(__name__)
_bridge=None


def start_local_shadow():
    global _bridge
    if _bridge is not None:return True
    if os.environ.get('POKER_LOCAL_TRAINER_SHADOW')!='1':return False
    try:
        path=Path(os.environ['POKER_LOCAL_TRAINER_SHADOW_PLAN'])
        if path.stat().st_size>1024*1024:raise ValueError('Plan exceeds local limit')
        from research.trainer_shadow_bridge import TrainerShadowBridge
        _bridge=TrainerShadowBridge(json.loads(path.read_text()))
        logger.info('LOCAL_TRAINER_SHADOW_ENABLED');return True
    except Exception:
        logger.warning('LOCAL_TRAINER_SHADOW_DISABLED_INVALID_PLAN');return False


def stop_local_shadow():
    global _bridge
    bridge=_bridge;_bridge=None
    if bridge is not None:bridge.close()


def observe(owner,state):
    bridge=_bridge
    if bridge is None:return
    try:bridge.observe(owner,state)
    except Exception:logger.warning('LOCAL_TRAINER_SHADOW_OBSERVE_FAILED')


def capture(owner,state,analysis):
    bridge=_bridge
    if bridge is None:return
    try:bridge.offer(owner,state,analysis)
    except Exception:logger.warning('LOCAL_TRAINER_SHADOW_CAPTURE_FAILED')


def local_diagnostics():
    """In-process local diagnostics only; deliberately not an HTTP endpoint."""
    bridge=_bridge
    if bridge is None:return {'enabled':False}
    return {'enabled':True,'bridge':bridge.stats(),'events':bridge.events(),'executor_events':bridge.executor.events()}
