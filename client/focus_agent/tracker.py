from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4


@dataclass(frozen=True)
class Application:
    app_name: str
    process_name: str


class SessionTracker:
    """One-second observations, bounded segments; suspend/time jumps never count as usage."""
    def __init__(self, segment_seconds=30, max_gap=5):
        self.segment_seconds, self.max_gap = segment_seconds, max_gap
        self.app = None
        self.start = self.last_wall = self.last_mono = None

    def _finish(self, end):
        if self.app is None or self.start is None or end <= self.start:
            return []
        return [{"id": str(uuid4()), "kind": "app_usage", "app_name": self.app.app_name,
                 "process_name": self.app.process_name,
                 "started_at": datetime.fromtimestamp(self.start, timezone.utc).isoformat(),
                 "ended_at": datetime.fromtimestamp(end, timezone.utc).isoformat(),
                 "duration_seconds": round(end - self.start, 6)}]

    def observe(self, app, wall, monotonic):
        events = []
        if self.last_mono is not None:
            gap, wall_gap = monotonic - self.last_mono, wall - self.last_wall
            continuous = 0 < gap <= self.max_gap and wall_gap > 0 and abs(wall_gap - gap) < 2
            if not continuous or app is None:
                events += self._finish(self.last_wall)
                self.app, self.start = None, None
            elif self.app is not None and (app != self.app or wall - self.start >= self.segment_seconds):
                events += self._finish(wall)
                self.app, self.start = None, None
        if self.app is None and app is not None:
            self.app, self.start = app, wall
        self.last_wall, self.last_mono = wall, monotonic
        return events

    def stop(self, wall, monotonic):
        return self.observe(None, wall, monotonic)
