"""Export a local decision snapshot for 2–6-player solver integration research.
No remote API, paid service or solver process is called.
From backend: PYTHONPATH=. .venv/bin/python research/export_solver_snapshot.py hand.json
"""
import argparse
import json
from pathlib import Path
from app.models.poker import HandState
from app.services.solver_snapshot import prepare_solver_snapshot, solver_availability

def export(raw):
    snapshot=prepare_solver_snapshot(HandState.model_validate(raw))
    return {'snapshot':snapshot,'availability':solver_availability(snapshot)}

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('decision_json',type=Path)
    args=parser.parse_args()
    print(json.dumps(export(json.loads(args.decision_json.read_text())),indent=2))
