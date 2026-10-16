from dataclasses import replace

import pytest

from focus_agent.app_colors import COLOR_IDS, color_for, default_color
from focus_agent.config import load_config, save_config
from focus_agent.network import ColorSyncUnavailable, Uploader
from focus_agent.store import EventStore
from test_client import config


def test_default_colors_are_stable_and_config_roundtrips(tmp_path):
    assert default_color("Chrome.EXE") == default_color("chrome") == default_color(r"C:\Apps\Chrome.exe")
    assert default_color("chrome") in COLOR_IDS
    assert color_for({"chrome": "teal"}, "CHROME.EXE") == "teal"
    first = config(app_colors={r"C:\Apps\Chrome.EXE": "teal", "code": "rose"})
    first.validate()
    assert first.app_colors == {"chrome.exe": "teal", "code": "rose"}
    path = tmp_path / "config.json"
    save_config(path, first, lambda text: text)
    assert load_config(path, lambda text: text).app_colors == first.app_colors


@pytest.mark.parametrize("colors", [{" ": "teal"}, {"app": "#ff0000"}, {"app": None}, [],
                                    {"App.EXE": "rose", "app.exe": "teal"}, {str(i): "rose" for i in range(501)}])
def test_invalid_colors_are_rejected(colors):
    with pytest.raises(ValueError):
        config(app_colors=colors).validate()


def test_color_sync_retries_after_outage_and_sends_empty_reset(tmp_path, monkeypatch):
    from focus_agent import network
    first = config(app_colors={"chrome": "teal"})
    uploader = Uploader(EventStore(tmp_path / "queue.db"), first)
    calls = []

    def request(current, path, body=None, method=None):
        assert path == "/api/v1/agent/app-colors" and method == "PUT"
        calls.append(body)
        if len(calls) == 1:
            raise RuntimeError("offline")
        return {"ok": True, "device_id": current.device_id, "app_colors": body["app_colors"]}

    monkeypatch.setattr(network, "request_json", request)
    with pytest.raises(RuntimeError, match="配色同步失败"):
        uploader.sync_colors(first)
    assert uploader.color_state is None
    assert uploader.sync_colors(first) == ""
    assert uploader.sync_colors(first) == "" and len(calls) == 2
    reset = replace(first, app_colors={})
    uploader.configure(reset)
    assert uploader.sync_colors(reset) == ""
    assert calls[-1]["app_colors"] == {} and len(calls) == 3


def test_old_server_color_warning_does_not_block_uploads(tmp_path, monkeypatch):
    from focus_agent import network
    first = config(app_colors={"chrome": "teal"})
    uploader = Uploader(EventStore(tmp_path / "queue.db"), first)

    def unavailable(*args, **kwargs):
        raise ColorSyncUnavailable("服务端不支持程序配色，请升级服务端")

    monkeypatch.setattr(network, "request_json", unavailable)
    assert "升级服务端" in uploader.sync_colors(first)
    assert uploader.sync_colors(replace(first, app_colors={})) == ""
