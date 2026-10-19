import json
import os
import time
from pathlib import Path

FAKE_MPV = str(Path(__file__).parent / "fake_mpv.py")


def read_log(path):
    if not os.path.exists(path):
        return []
    return [json.loads(l) for l in Path(path).read_text().splitlines() if l.strip()]


def wait_for(predicate, timeout=5.0, step=0.05):
    end = time.time() + timeout
    while time.time() < end:
        if predicate():
            return True
        time.sleep(step)
    return False
