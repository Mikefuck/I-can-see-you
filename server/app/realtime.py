"""Coalesced change notifications for the single-worker web server.

Only invalidations travel over SSE. Existing JSON endpoints remain responsible
for reading data and enforcing the viewer's current permissions.
"""
import asyncio
from contextlib import contextmanager


HEARTBEAT_SECONDS = 15
RETRY_MILLISECONDS = 3000


class ChangeBroker:
    def __init__(self):
        self.loop = None
        self.revision = 0
        self.versions = {}
        self.listeners = set()

    def start(self):
        self.loop = asyncio.get_running_loop()
        self.revision = 0
        self.versions.clear()

    def close(self):
        self.loop = None
        for listener in self.listeners:
            listener.set()

    def publish(self, owner_id, *, history=False, metadata=False):
        """May be called from sync FastAPI routes, after their transaction commits."""
        loop = self.loop
        if loop is not None and not loop.is_closed():
            loop.call_soon_threadsafe(self._publish, owner_id, history, metadata)

    def _publish(self, owner_id, history, metadata):
        self.revision += 1
        self.versions[owner_id, "live"] = self.revision
        if history:
            self.versions[owner_id, "history"] = self.revision
        if metadata:
            self.versions[owner_id, "metadata"] = self.revision
        for listener in self.listeners:
            listener.set()

    @contextmanager
    def subscribe(self):
        listener = asyncio.Event()
        self.listeners.add(listener)
        try:
            yield listener
        finally:
            self.listeners.discard(listener)

    def areas_since(self, revision, owners):
        # Owner 0 denotes a site-wide change such as the retention policy.
        return sorted({area for (owner, area), version in self.versions.items()
                       if version > revision and (owner == 0 or owner in owners)})
