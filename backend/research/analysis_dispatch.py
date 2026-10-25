"""Route bounded jobs to separate contracts on the same single-worker queue."""
from research import analysis_contract, turn_analysis
from research.lesson_values import analyze as analyze_river


def protocol_for(request):
    snapshot = request.get('snapshot') if isinstance(request, dict) else None
    return turn_analysis if isinstance(snapshot, dict) and snapshot.get('street') == 'turn' else analysis_contract


def analyze(request, limits=None, *, cancel_event=None):
    if protocol_for(request) is turn_analysis:
        return turn_analysis.analyze(request, limits, cancel_event=cancel_event)
    return analyze_river(request, limits, cancel_event=cancel_event)
