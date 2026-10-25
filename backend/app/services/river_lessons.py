"""Explicit opt-in for bounded river review; research modules are absent from the default import path."""
import logging
import os

_service = None
_reason = 'LESSON_NOT_ENABLED'


def start_river_lessons():
    global _service, _reason
    if _service is not None:
        return True
    if os.environ.get('POKER_RIVER_LESSONS_ENABLED', os.environ.get('POKER_LOCAL_RIVER_LESSONS')) != '1':
        return False
    try:
        from research.native_cfr import load_library
        load_library()
        from research.river_lessons import RiverLessons
        from app.api.training import store
        _service = RiverLessons(store=store)
        _reason = None
        return True
    except Exception:
        _reason = 'LESSON_ENGINE_UNAVAILABLE'
        logging.getLogger(__name__).warning('RIVER_LESSONS_KERNEL_UNAVAILABLE')
        return False


def stop_river_lessons():
    global _service
    service, _service = _service, None
    if service is not None:
        service.close()


def catalog():
    if _service is None:
        return {'enabled': False, 'version': None, 'lessons': [], 'reason': _reason}
    return _service.catalog()


def service():
    return _service
