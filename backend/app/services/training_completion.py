"""Persist completion evidence without retaining final or opponent cards."""
from collections import OrderedDict
import logging
from threading import RLock

_saved = OrderedDict()
_lock = RLock()


def observe_completed(owner, state):
    if owner is None or state is None or state.result is None:
        return
    key = (owner, state.hand_id)
    with _lock:
        if key in _saved:
            return
        try:
            # Lazy import avoids the hand/training route initialization cycle.
            from app.api.training import store
            store.mark_hand_completed(owner, state)
        except Exception:
            # Failure to index a review must not undo a completed game action.
            # A subsequent state read retries the idempotent update.
            logging.getLogger(__name__).warning('TRAINING_COMPLETION_NOT_SAVED')
            return
        # Repeated reads of a completed hand need no further database round trip.
        _saved[key] = True
        while len(_saved) > 1000:
            _saved.popitem(last=False)
