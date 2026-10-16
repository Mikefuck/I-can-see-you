"""Measure request-body bytes with synthetic records; never contacts a server or reads user data."""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from focus_agent import __version__
from focus_agent.network import encode_json


def sample_payload(count):
    origin = datetime(2026, 10, 16, tzinfo=timezone.utc)
    events = []
    apps = [("Visual Studio Code", "Code.exe"), ("浏览器", "chrome.exe"), ("文件资源管理器", "explorer.exe")]
    for index in range(count):
        start = origin + timedelta(seconds=30 * index, microseconds=123456)
        name, process = apps[(index // 20) % len(apps)]
        events.append({"id": str(uuid5(NAMESPACE_URL, f"focusledger-upload-benchmark/{index}")),
                       "kind": "app_usage", "app_name": name, "process_name": process,
                       "started_at": start.isoformat(), "ended_at": (start + timedelta(seconds=30)).isoformat(),
                       "duration_seconds": 30.0})
    return {"schema_version": 1,
            "device": {"id": str(uuid5(NAMESPACE_URL, "focusledger-upload-benchmark/device")),
                       "name": "工作电脑", "platform": "windows", "agent_version": __version__},
            "events": events}


def legacy_size(body):
    return len(json.dumps(body, ensure_ascii=False).encode("utf-8"))


def measurements():
    rows = []
    for label, count in (("空心跳", 0), ("常规定时上传（1条）", 1), ("已协商压缩的补传（500条）", 500)):
        body = sample_payload(count)
        encoded, _ = encode_json(body, compress=True)
        old_batches = [{**body, "events": body["events"][offset:offset + 200]}
                       for offset in range(0, max(1, count), 200)]
        rows.append((label, sum(legacy_size(part) for part in old_batches), len(encoded), len(old_batches), 1))
    body = sample_payload(1200)
    old_total = new_total = 0
    for offset in range(0, 1200, 200):
        old_total += legacy_size({**body, "events": body["events"][offset:offset + 200]})
    for offset in range(0, 1200, 500):
        # Include the first plain request used to discover compression after a restart.
        encoded, _ = encode_json({**body, "events": body["events"][offset:offset + 500]}, compress=offset > 0)
        new_total += len(encoded)
    rows.append(("重启后补传10小时（1200条）", old_total, new_total, 6, 3))
    return rows


if __name__ == "__main__":
    for label, before, after, old_requests, new_requests in measurements():
        print(f"{label}: {before:,} -> {after:,} bytes; 减少 {1 - after / before:.1%}; "
              f"请求 {old_requests} -> {new_requests}")
    print("仅统计请求体；使用合成数据，未计入 HTTP 请求头、TLS 和失败重试。实际比例取决于应用名与记录分布。")
