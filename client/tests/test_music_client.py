import asyncio
import time
from types import SimpleNamespace as Obj

import pytest

from focus_agent.music import read_track
from focus_agent import network
from focus_agent.store import EventStore
from test_client import config


def session(title, state=4, source="player.exe", media_type=1, fail=False):
    async def properties():
        if fail:
            raise OSError("Player exited")
        return Obj(title=title, artist="歌手", album_title="专辑", playback_type=media_type)
    return Obj(source_app_user_model_id=source, get_playback_info=lambda: Obj(playback_status=state),
               try_get_media_properties_async=properties)


def test_windows_prefers_playing_music_over_paused_current_and_ignores_video():
    paused = session("暂停的歌", 5)
    playing = session("正在播放", source="music.exe")
    manager = Obj(get_current_session=lambda: paused,
                  get_sessions=lambda: [paused, session("视频", media_type=2), session("故障", fail=True), playing])
    track = asyncio.run(read_track(manager))
    assert track["title"] == "正在播放" and track["state"] == "playing"
    manager.get_sessions = lambda: [paused]
    assert asyncio.run(read_track(manager))["state"] == "paused"
    manager.get_sessions = lambda: [session("停止", state=3), session("  ")]
    assert asyncio.run(read_track(manager)) is None


def test_windows_player_identifier_does_not_upload_full_executable_path():
    manager = Obj(get_current_session=lambda: None,
                  get_sessions=lambda: [session("歌曲", source="C:/Users/private/Music/player.exe")])
    track = asyncio.run(read_track(manager))
    assert track["process_name"] == track["app_name"] == "player.exe"


@pytest.mark.parametrize("supported", [True, False])
def test_music_upload_negotiates_and_does_not_block_older_server(tmp_path, monkeypatch, supported):
    uploader = network.Uploader(EventStore(tmp_path / "music.db"), config())
    sent = []
    def request(current, path, body=None, method=None, **kwargs):
        if path.endswith("/check"):
            return {"features": ["music"] if supported else []}
        if path.endswith("/app-aliases"):
            return {"ok": True, "device_id": current.device_id, "app_aliases": current.app_aliases}
        if path.endswith("/app-colors"):
            return {"ok": True, "device_id": current.device_id, "app_colors": current.app_colors}
        sent.append(body)
        uploader.stop()
        return {"acknowledged_ids": []}
    monkeypatch.setattr(network, "request_json", request)
    track = {"title": "测试歌曲", "artist": "歌手", "album": "", "app_name": "播放器", "process_name": "music.exe", "state": "playing"}
    uploader.observe_music(track, time.time())
    uploader._run()
    assert ("music" in sent[0]) == supported
    if supported:
        assert sent[0]["music"]["track"] == track
    uploader.observe_music(None, time.time())
    assert uploader.music["track"] is None


def test_music_changes_wake_uploader_and_disabled_config_clears_it(tmp_path):
    from dataclasses import replace
    uploader = network.Uploader(EventStore(tmp_path / "music.db"), config())
    track = {"title": "测试歌曲", "state": "playing"}
    uploader.observe_music(track, time.time())
    assert uploader.wake.is_set()
    uploader.wake.clear()
    uploader.observe_music(track, time.time())
    assert not uploader.wake.is_set()
    uploader.observe_music({**track, "state": "paused"}, time.time())
    assert uploader.wake.is_set()
    uploader.configure(replace(uploader.config, music_enabled=False))
    uploader.observe_music(track, time.time())
    assert uploader.music["track"] is None
