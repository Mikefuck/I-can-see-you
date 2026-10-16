"""Read models behind the web pages: who may be seen, what each device is doing, activity runs.

Times inside run and status lists are whole seconds relative to a stated base, which keeps a
day of activity compact. Calendar days are left to the browser, the only side that knows the
viewer's time zone.
"""
from collections import defaultdict
import json
from .aliases import device_aliases, display_name
from .app_colors import color_for, device_colors

# The client uploads every 10–300 s (default 30) and sends an empty heartbeat when idle.
ONLINE_SECONDS = 330
# Usage that ended this close to the latest upload means someone is at the device right now.
ACTIVE_SECONDS = 90
# Tracker segments of one app are contiguous and at most 30 s long; join them into runs.
RUN_GAP = 2.0
# A continuous stretch survives app switches and pauses of up to a minute.
STREAK_GAP = 60.0
# Long enough to contain the viewer's local midnight in every time zone, DST included.
BOARD_WINDOW = 26 * 3600
MAX_SPAN = 367 * 86400


class Apps:
    """Interns (app name, process) pairs so payloads repeat small indexes instead of names."""
    def __init__(self, db=None):
        self.db, self.device_colors = db, {}
        self.index, self.items = {}, []
        self.colors = []

    def __call__(self, name, process, device_id=""):
        if device_id not in self.device_colors:
            self.device_colors[device_id] = device_colors(self.db, device_id) if self.db is not None else {}
        color = color_for(self.device_colors[device_id], process)
        key = (name, process, color)
        if key not in self.index:
            self.index[key] = len(self.items)
            self.items.append([name, process])
            self.colors.append(color)
        return self.index[key]


def visible_people(db, viewer):
    """Guests see public accounts; signed-in members see every enabled account."""
    viewer_id = viewer["id"] if viewer else None
    return db.execute(
        "SELECT id,username,shared FROM users WHERE enabled=1 AND (shared=1 OR ?=1) "
        "ORDER BY id IS NOT ?, username COLLATE NOCASE", (viewer is not None, viewer_id)).fetchall()


def find_person(db, viewer, username):
    return db.execute("SELECT id,username,shared FROM users WHERE username=? AND enabled=1 AND (shared=1 OR ?=1)",
                      (username, viewer is not None)).fetchone()


def devices_of(db, user_ids, cutoff):
    if not user_ids:
        return []
    marks = ",".join("?" * len(user_ids))
    return db.execute(f"SELECT * FROM devices WHERE user_id IN ({marks}) AND last_seen>? ORDER BY first_seen",
                      [*user_ids, cutoff]).fetchall()


def device_summary(db, device, now):
    """Live state of one device, derived from its last contact, last usage and last power event."""
    aliases = device_aliases(db, device["id"])
    recent = db.execute("SELECT app_name,process_name,started_at,ended_at FROM events WHERE device_id=? "
                        "ORDER BY ended_at DESC LIMIT 1440", (device["id"],))
    last = None
    for row in recent:
        name = display_name(aliases, row["process_name"], row["app_name"])
        if last is None:
            last = {"app": name, "process": row["process_name"],
                    "since": row["started_at"], "until": row["ended_at"]}
        elif (name, row["process_name"]) == (last["app"], last["process"]) \
                and last["since"] - row["ended_at"] <= RUN_GAP:
            last["since"] = row["started_at"]
        else:
            break
    recent.close()
    foreground = db.execute("SELECT * FROM device_foreground WHERE device_id=?", (device["id"],)).fetchone()
    if foreground and (now - foreground["observed_at"] > ONLINE_SECONDS or
                       foreground["observed_at"] < device["last_seen"] - ACTIVE_SECONDS):
        foreground = None
    if foreground and foreground["app_name"] is not None:
        last = {"app": display_name(aliases, foreground["process_name"], foreground["app_name"]),
                "process": foreground["process_name"], "since": foreground["since"], "until": foreground["observed_at"]}
    if last:
        last["color"] = color_for(device_colors(db, device["id"]), last["process"])
    lifecycle = db.execute("SELECT occurred_at,reason FROM status_events WHERE device_id=? AND reason<>'periodic' "
                           "ORDER BY occurred_at DESC LIMIT 1", (device["id"],)).fetchone()
    battery = db.execute("SELECT occurred_at,battery_percent,charging,ac_online,battery_life_seconds FROM status_events "
                         "WHERE device_id=? AND battery_percent IS NOT NULL ORDER BY occurred_at DESC LIMIT 1",
                         (device["id"],)).fetchone()
    last_seen, last_use = device["last_seen"], last["until"] if last else None
    # A shutdown or sleep only counts while nothing was used or uploaded after it.
    if lifecycle and lifecycle["reason"] in ("shutdown", "suspend") and (last_use or 0) <= lifecycle["occurred_at"] + 5 \
            and last_seen <= lifecycle["occurred_at"] + 120 \
            and (foreground is None or foreground["observed_at"] <= lifecycle["occurred_at"]):
        state, since = ("off" if lifecycle["reason"] == "shutdown" else "asleep"), lifecycle["occurred_at"]
    elif now - last_seen > ONLINE_SECONDS:
        state, since = "offline", last_seen
    elif foreground:
        state, since = ("active" if foreground["app_name"] is not None else "idle"), foreground["since"]
    elif last_use and last_use >= last_seen - ACTIVE_SECONDS:
        state, since = "active", last["since"]
    else:
        state, since = "idle", last_use
    music = db.execute("SELECT observed_at,track FROM device_music WHERE device_id=?", (device["id"],)).fetchone()
    current_music = None
    if (music and music["track"] and now - last_seen <= ONLINE_SECONDS
            and now - music["observed_at"] <= ONLINE_SECONDS
            and music["observed_at"] >= last_seen - ACTIVE_SECONDS):
        current_music = json.loads(music["track"])
        current_music["app_name"] = display_name(aliases, current_music["process_name"], current_music["app_name"])
        current_music["observed_at"] = music["observed_at"]
    return {
        "id": device["id"], "name": device["name"], "platform": device["platform"],
        "version": device["agent_version"], "first_seen": device["first_seen"], "last_seen": last_seen,
        "state": state, "since": since, "last": last, "music": current_music,
        "battery": None if not battery else {
            "at": battery["occurred_at"], "percent": battery["battery_percent"],
            "charging": None if battery["charging"] is None else bool(battery["charging"]),
            "ac": None if battery["ac_online"] is None else bool(battery["ac_online"]),
            "life": battery["battery_life_seconds"]},
    }


def live_view(db, viewer, now, cutoff, people=None):
    """Current device summaries only; frequent refreshes need no timeline or ranking scan."""
    people = visible_people(db, viewer) if people is None else people
    owned = defaultdict(list)
    for device in devices_of(db, [person["id"] for person in people], cutoff):
        owned[device["user_id"]].append(device_summary(db, device, now))
    return {
        "now": now, "authenticated": viewer is not None,
        "people": [{"username": person["username"], "self": bool(viewer and person["id"] == viewer["id"]),
                    "shared": bool(person["shared"]), "devices": owned[person["id"]]} for person in people],
    }


def load_runs(db, where, params, start, end):
    """Join contiguous same-app segments per device into runs, clipped to [start, end]."""
    rows = db.execute("SELECT device_id,app_name,process_name,started_at,ended_at FROM events "
                      f"WHERE {where} AND ended_at>? AND started_at<? ORDER BY device_id,started_at",
                      [*params, start, end])
    runs = []
    current_device, aliases = None, {}
    for device, app, process, s, e in rows:
        if device != current_device:
            current_device, aliases = device, device_aliases(db, device)
        app = display_name(aliases, process, app)
        s, e = max(s, start), min(e, end)
        last = runs[-1] if runs else None
        if last and last[0] == device and last[1] == app and last[2] == process and s - last[4] <= RUN_GAP:
            last[4] = max(last[4], e)
        else:
            runs.append([device, app, process, s, e])
    return runs


def board(db, viewer, now, cutoff, since=None):
    """Everyone the viewer may see, each device with its state and today's runs."""
    base = now - BOARD_WINDOW if since is None else min(max(since, now - BOARD_WINDOW), now)
    start = max(base, cutoff)
    people = visible_people(db, viewer)
    ids = [person["id"] for person in people]
    if not ids:
        return {"now": now, "base": base, "authenticated": viewer is not None, "apps": [], "app_colors": [], "people": []}
    marks = ",".join("?" * len(ids))
    apps, runs, lifecycle = Apps(db), defaultdict(list), defaultdict(list)
    for device, app, process, s, e in load_runs(db, f"user_id IN ({marks})", ids, start, now):
        runs[device].append([round(s - base), round(e - base), apps(app, process, device)])
    for device, at, reason in db.execute(
            f"SELECT device_id,occurred_at,reason FROM status_events WHERE user_id IN ({marks}) "
            "AND reason<>'periodic' AND occurred_at>? AND occurred_at<=? ORDER BY occurred_at", [*ids, start, now]):
        lifecycle[device].append([round(at - base), reason])
    owned = defaultdict(list)
    for device in devices_of(db, ids, cutoff):
        summary = device_summary(db, device, now)
        summary["runs"], summary["marks"] = runs[device["id"]], lifecycle[device["id"]]
        owned[device["user_id"]].append(summary)
    return {"now": now, "base": base, "authenticated": viewer is not None, "apps": apps.items, "app_colors": apps.colors,
            "people": [{"username": person["username"], "self": bool(viewer and person["id"] == viewer["id"]),
                        "shared": bool(person["shared"]), "devices": owned[person["id"]]} for person in people]}


def longest_streak(runs):
    best, current = None, None
    for s, e in sorted((run[3], run[4]) for run in runs):
        if current and s - current[1] <= STREAK_GAP:
            current[1] = max(current[1], e)
            continue
        if current and (best is None or current[1] - current[0] > best[1] - best[0]):
            best = current
        current = [s, e]
    if current and (best is None or current[1] - current[0] > best[1] - best[0]):
        best = current
    return best


def person_view(db, person, viewer, now, cutoff, start, end, device_id=""):
    """One person's activity in [start, end): exact runs for a day or two, time bins beyond that."""
    devices = devices_of(db, [person["id"]], cutoff)
    span, low, high = end - start, max(start, cutoff), min(end, now)
    bin_size = 0 if span <= 50 * 3600 else 900 if span <= 32 * 86400 else 1800
    where, params = ("user_id=? AND device_id=?", [person["id"], device_id]) if device_id else ("user_id=?", [person["id"]])
    runs = load_runs(db, where, params, low, high) if high > low else []
    apps, totals, ranking = Apps(db), defaultdict(float), defaultdict(float)
    for device, app, process, s, e in runs:
        totals[device] += e - s
        ranking[apps(app, process, device)] += e - s
    ordered = sorted(ranking.items(), key=lambda item: -item[1])
    payload = {
        "now": now, "start": start, "end": end, "bin": bin_size, "device": device_id,
        "person": {"username": person["username"], "self": bool(viewer and person["id"] == viewer["id"]), "shared": bool(person["shared"])},
        "devices": [device_summary(db, device, now) for device in devices],
        "apps": apps.items,
        "app_colors": apps.colors,
        "totals": {device: round(seconds) for device, seconds in totals.items()},
        "ranking": [[index, round(seconds)] for index, seconds in ordered[:40]],
        "other": round(sum(seconds for _, seconds in ordered[40:])),
        "records": [[device, round(s - start), round(e - start), apps(app, process, device)]
                    for device, app, process, s, e in sorted(runs, key=lambda run: -run[4])[:100]],
    }
    streak = longest_streak(runs)
    payload["streak"] = [round(streak[0] - start), round(streak[1] - start)] if streak else None
    if bin_size:
        bins = defaultdict(lambda: defaultdict(float))
        for device, app, process, s, e in runs:
            index, t = apps(app, process, device), s
            while t < e:
                slot = int((t - start) // bin_size)
                edge = max(min(e, start + (slot + 1) * bin_size), t + 1e-6)
                bins[slot][index] += edge - t
                t = edge
        payload["bins"] = [[slot, round(sum(share.values())), max(share, key=share.get)]
                           for slot, share in sorted(bins.items())]
    else:
        payload["runs"] = defaultdict(list)
        for device, app, process, s, e in runs:
            payload["runs"][device].append([round(s - start), round(e - start), apps(app, process, device)])
    # Battery readings draw a line over a day; longer ranges only list power events.
    query = ("SELECT device_id,occurred_at,reason,battery_percent,charging,ac_online FROM status_events "
             f"WHERE {where} AND occurred_at>? AND occurred_at<=?")
    query += " AND reason<>'periodic' ORDER BY occurred_at DESC LIMIT 200" if bin_size else \
        " ORDER BY occurred_at DESC LIMIT 2000"
    rows = db.execute(query, [*params, low, high]).fetchall() if high > low else []
    payload["status"] = [[row[0], round(row[1] - start), row[2], row[3],
                          None if row[4] is None else bool(row[4]), None if row[5] is None else bool(row[5])]
                         for row in reversed(rows)]
    return payload
