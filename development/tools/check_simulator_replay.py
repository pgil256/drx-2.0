"""Verify a recorded simulator core run: python .../check_simulator_replay.py SESSION.jsonl."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from simulator.session.recording import check_replay


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("recording", type=Path)
    print(json.dumps(check_replay(parser.parse_args().recording), indent=2))
