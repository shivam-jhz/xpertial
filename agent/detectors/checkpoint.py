"""
XPERTIAL – Checkpoint Tracker
-------------------------------
Watches a directory (or receives explicit checkpoint events) and
records the last successful checkpoint step + timestamp.
No complex recovery — just awareness.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional


@dataclass
class CheckpointStatus:
    last_step: Optional[int] = None
    last_saved_at: Optional[float] = None
    last_path: Optional[str] = None
    total_checkpoints: int = 0
    save_failed: bool = False
    failure_reason: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


class CheckpointTracker:
    """
    Call `on_save(step, path)` after each checkpoint write.
    Call `on_save_failed(step, reason)` if the write fails.
    """

    def __init__(self, watch_dir: Optional[str] = None):
        self.status = CheckpointStatus()
        self._watch_dir = Path(watch_dir) if watch_dir else None

        # If a directory is given, try to detect existing checkpoints
        if self._watch_dir and self._watch_dir.exists():
            self._scan_existing()

    def on_save(self, step: int, path: Optional[str] = None):
        self.status.last_step = step
        self.status.last_saved_at = time.time()
        self.status.last_path = path
        self.status.total_checkpoints += 1
        self.status.save_failed = False
        self.status.failure_reason = None

    def on_save_failed(self, step: int, reason: str = ""):
        self.status.save_failed = True
        self.status.failure_reason = reason

    def _scan_existing(self):
        """Find the highest step number from checkpoint file names."""
        import re
        highest = -1
        for p in self._watch_dir.glob("**/*"):
            m = re.search(r"step[_-]?(\d+)", p.name, re.IGNORECASE)
            if m:
                s = int(m.group(1))
                if s > highest:
                    highest = s
                    self.status.last_step = s
                    self.status.last_path = str(p)
