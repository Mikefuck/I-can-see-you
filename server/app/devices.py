"""Account-scoped device names, with client IDs retained for old queues."""

import json
import re
from uuid import NAMESPACE_URL, uuid4, uuid5

from fastapi import HTTPException


MACHINE_HEADER = "X-FocusLedger-Machine-ID"


def request_machine_id(request):
    value = request.headers.get(MACHINE_HEADER, "")
    if value and not re.fullmatch(r"[0-9a-f]{64}", value):
        raise HTTPException(422, "电脑识别值格式无效")
    return value


def name_conflict():
    raise HTTPException(409, {"code": "device_name_conflict",
                              "message": "设备名称已被占用，请在设置中修改设备名称后重试"})


def event_identity(db, client_id, event_id):
    row = db.execute("SELECT canonical_event_id FROM device_event_ids WHERE client_id=? AND event_id=?",
                     (client_id, event_id)).fetchone()
    return row[0] if row else event_id


def merge_devices(db, target_id, source_id):
    """Keep history, queue identities and the most recent metadata when consolidating names."""
    target = db.execute("SELECT * FROM devices WHERE id=?", (target_id,)).fetchone()
    source = db.execute("SELECT * FROM devices WHERE id=?", (source_id,)).fetchone()
    for table, other in (("events", "status_events"), ("status_events", "events")):
        # Resolve only UUID collisions individually, in bounded chunks. Normal history is
        # moved in one statement, so a year's worth of records need not be loaded into RAM.
        while True:
            rows = db.execute(f"SELECT s.* FROM {table} s WHERE s.device_id=? AND ("
                              f"EXISTS(SELECT 1 FROM {table} t WHERE t.user_id=s.user_id AND t.device_id=? AND t.event_id=s.event_id) OR "
                              f"EXISTS(SELECT 1 FROM {other} t WHERE t.user_id=s.user_id AND t.device_id=? AND t.event_id=s.event_id)) LIMIT 500",
                              (source_id, target_id, target_id)).fetchall()
            if not rows:
                break
            for row in rows:
                previous = db.execute(f"SELECT * FROM {table} WHERE user_id=? AND device_id=? AND event_id=?",
                                      (source["user_id"], target_id, row["event_id"])).fetchone()
                if previous and all(previous[key] == row[key] for key in row.keys()
                                    if key not in {"row_id", "device_id", "payload_hash"}):
                    db.execute(f"DELETE FROM {table} WHERE row_id=?", (row["row_id"],))
                    continue
                # Old devices could use the same event UUID for different data. Preserve both,
                # and remember the translation so a pending old upload remains idempotent.
                event_id = str(uuid5(NAMESPACE_URL, f"focusledger:{source_id}:{table}:{row['event_id']}"))
                db.execute("UPDATE device_event_ids SET canonical_event_id=? WHERE canonical_event_id=? "
                           "AND client_id IN (SELECT id FROM device_clients WHERE device_id=?)",
                           (event_id, row["event_id"], source_id))
                db.execute("INSERT INTO device_event_ids(client_id,event_id,canonical_event_id) "
                           "SELECT id,?,? FROM device_clients WHERE device_id=? "
                           "ON CONFLICT(client_id,event_id) DO NOTHING", (row["event_id"], event_id, source_id))
                db.execute(f"UPDATE {table} SET device_id=?,event_id=? WHERE row_id=?",
                           (target_id, event_id, row["row_id"]))
        db.execute(f"UPDATE {table} SET device_id=? WHERE device_id=?", (target_id, source_id))
    aliases = {}
    for device in sorted((target, source), key=lambda item: (item["last_seen"], item["id"])):
        saved = db.execute("SELECT aliases FROM device_app_aliases WHERE device_id=?", (device["id"],)).fetchone()
        if saved:
            aliases.update(json.loads(saved[0]))
    if aliases:
        db.execute("INSERT INTO device_app_aliases VALUES(?,?) ON CONFLICT(device_id) "
                   "DO UPDATE SET aliases=excluded.aliases", (target_id, json.dumps(aliases, ensure_ascii=False)))
    colors = {}
    for device in sorted((target, source), key=lambda item: (item["last_seen"], item["id"])):
        saved = db.execute("SELECT colors FROM device_app_colors WHERE device_id=?", (device["id"],)).fetchone()
        if saved:
            colors.update(json.loads(saved[0]))
    if colors:
        db.execute("INSERT INTO device_app_colors VALUES(?,?) ON CONFLICT(device_id) "
                   "DO UPDATE SET colors=excluded.colors", (target_id, json.dumps(colors)))
    latest = max((target, source), key=lambda item: (item["last_seen"], item["id"]))
    db.execute("INSERT INTO device_foreground(device_id,observed_at,since,app_name,process_name) "
               "SELECT ?,observed_at,since,app_name,process_name FROM device_foreground WHERE device_id=? "
               "ON CONFLICT(device_id) DO UPDATE SET observed_at=excluded.observed_at,since=excluded.since,"
               "app_name=excluded.app_name,process_name=excluded.process_name "
               "WHERE excluded.observed_at>device_foreground.observed_at", (target_id, source_id))
    db.execute("UPDATE devices SET first_seen=?,last_seen=?,platform=?,agent_version=? WHERE id=?",
               (min(target["first_seen"], source["first_seen"]), latest["last_seen"],
                latest["platform"], latest["agent_version"], target_id))
    db.execute("INSERT INTO device_computers(device_id,machine_id) "
               "SELECT ?,machine_id FROM device_computers WHERE device_id=? "
               "ON CONFLICT(device_id) DO NOTHING", (target_id, source_id))
    db.execute("UPDATE device_clients SET device_id=? WHERE device_id=?", (target_id, source_id))
    db.execute("DELETE FROM devices WHERE id=?", (source_id,))


def migrate_device_names(db):
    db.execute("INSERT INTO device_clients(id,device_id) SELECT id,id FROM devices WHERE 1 "
               "ON CONFLICT(id) DO NOTHING")
    # Remove surrounding whitespace just as the client does; preserve legacy blank names.
    devices = db.execute("SELECT * FROM devices ORDER BY first_seen,id").fetchall()
    names = {}
    for device in devices:
        name = device["name"].strip() or device["name"]
        key = (device["user_id"], name)
        if key in names:
            merge_devices(db, names[key], device["id"])
        else:
            names[key] = device["id"]
            db.execute("UPDATE devices SET name=? WHERE id=?", (name, device["id"]))
    db.execute("CREATE UNIQUE INDEX IF NOT EXISTS devices_owner_name ON devices(user_id,name)")


def register_device(db, user_id, device, machine_id, now):
    client_id = str(device.id)
    current = db.execute("SELECT d.* FROM devices d JOIN device_clients c ON c.device_id=d.id WHERE c.id=?",
                         (client_id,)).fetchone()
    if current is None:
        current = db.execute("SELECT * FROM devices WHERE id=?", (client_id,)).fetchone()
    if current and current["user_id"] != user_id:
        raise HTTPException(409, "设备已属于其他账户，请在客户端更换设备身份")
    named = db.execute("SELECT * FROM devices WHERE user_id=? AND name=?", (user_id, device.name)).fetchone()

    def other_computer(row):
        known = db.execute("SELECT machine_id FROM device_computers WHERE device_id=?", (row["id"],)).fetchone()
        return machine_id and known and known[0] != machine_id

    if current and other_computer(current):
        # Legacy same-name IDs may have been consolidated before either PC upgraded.
        # The second PC can recover by choosing its own name, without moving the first PC's history.
        if named and named["id"] == current["id"]:
            name_conflict()
        current = None
    if named:
        if other_computer(named):
            name_conflict()
        if (not current or current["id"] != named["id"]) and not machine_id:
            # A legacy client without a computer identity cannot safely claim another ID's name.
            name_conflict()
        if current and current["id"] != named["id"]:
            merge_devices(db, named["id"], current["id"])
        device_id = named["id"]
    else:
        device_id = current["id"] if current else client_id
        if not current and db.execute("SELECT 1 FROM devices WHERE id=?", (device_id,)).fetchone():
            device_id = str(uuid4())
    db.execute("INSERT INTO devices VALUES(?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
               "name=excluded.name,platform=excluded.platform,agent_version=excluded.agent_version,last_seen=excluded.last_seen",
               (device_id, user_id, device.name, device.platform, device.agent_version, now, now))
    db.execute("INSERT INTO device_clients(id,device_id) VALUES(?,?) ON CONFLICT(id) "
               "DO UPDATE SET device_id=excluded.device_id", (client_id, device_id))
    if machine_id:
        db.execute("INSERT INTO device_computers(device_id,machine_id) VALUES(?,?) "
                   "ON CONFLICT(device_id) DO NOTHING", (device_id, machine_id))
    return device_id
