"""Append a shared monotonic timeline for real-game latency diagnosis."""
import json
from pathlib import Path
import threading
import time


class Timeline:
    def __init__(self, output):
        self.path = Path(output)/'latency.jsonl'
        self.lock = threading.Lock()

    def emit(self, event, **fields):
        record = dict(event=event, wall_s=time.time(), monotonic_s=time.monotonic(), **fields)
        with self.lock, self.path.open('a') as stream:
            stream.write(json.dumps(record)+'\n')