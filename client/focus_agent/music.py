"""Read metadata published by Windows media sessions, without capturing audio."""
import asyncio
import logging
import threading
import time


def text(value, limit=300):
    return str(value or "").strip()[:limit]


async def read_track(manager):
    # Prefer a playing session over a paused current session. Never infer playback
    # from a window title, and never let one disappearing player hide another.
    current = manager.get_current_session()
    sessions = list(manager.get_sessions())
    if current is not None:
        sessions.sort(key=lambda session: session.source_app_user_model_id != current.source_app_user_model_id)
    candidates = []
    for session in sessions:
        try:
            state = int(session.get_playback_info().playback_status)
            if state in (4, 5):  # Playing / Paused in the Windows SDK.
                candidates.append((state != 4, session))
        except Exception:
            continue
    for paused, session in sorted(candidates, key=lambda item: item[0]):
        try:
            properties = await asyncio.wait_for(session.try_get_media_properties_async(), 3)
            title = text(properties.title)
            # Explicit video/image sessions are not music. Some players omit type.
            media_type = properties.playback_type
            if not title or (media_type is not None and int(media_type) != 1):
                continue
            source = text(session.source_app_user_model_id, 2048).replace("/", "\\").rsplit("\\", 1)[-1][:200]
            if not source:
                continue
            return {"title": title, "artist": text(properties.artist), "album": text(properties.album_title),
                    "app_name": source, "process_name": source, "state": "paused" if paused else "playing"}
        except Exception:
            continue
    return None


class MusicReader:
    """All WinRT calls stay on a worker; disabling invalidates in-flight reads."""
    def __init__(self, observe):
        self.observe = observe
        self.condition = threading.Condition()
        self.enabled = False
        self.closed = False
        self.revision = 0
        self.status = "音乐同步已暂停"
        self.thread = threading.Thread(target=self._run, name="focus-music", daemon=True)
        self.thread.start()

    def set_enabled(self, enabled):
        with self.condition:
            if self.enabled == enabled:
                return
            self.enabled = enabled
            self.revision += 1
            if not enabled:
                self.status = "音乐同步已暂停"
                self.observe(None, time.time())
            self.condition.notify_all()

    def stop(self):
        with self.condition:
            self.closed = True
            self.enabled = False
            self.revision += 1
            self.condition.notify_all()

    def _run(self):
        asyncio.run(self._poll())

    async def _poll(self):
        manager = None
        while True:
            with self.condition:
                self.condition.wait_for(lambda: self.closed or self.enabled)
                if self.closed:
                    return
                revision = self.revision
            try:
                if manager is None:
                    from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager
                    # These projections support iteration of GetSessions and media type.
                    import winrt.windows.foundation.collections  # noqa: F401
                    import winrt.windows.media  # noqa: F401
                    manager = await asyncio.wait_for(GlobalSystemMediaTransportControlsSessionManager.request_async(), 5)
                track = await read_track(manager)
                status = ("已暂停 · " if track and track["state"] == "paused" else "正在听 · ") + track["title"] if track else "暂无可读取的音乐播放信息"
                if track and track["artist"]:
                    status += " · " + track["artist"]
            except Exception:
                logging.debug("Windows media session unavailable", exc_info=True)
                manager, track, status = None, None, "音乐信息不可用，请确认播放器已开启系统媒体控制"
            with self.condition:
                if self.closed:
                    return
                if self.enabled and revision == self.revision:
                    self.status = status
                    self.observe(track, time.time())
                self.condition.wait(timeout=2)
