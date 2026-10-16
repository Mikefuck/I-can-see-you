package com.focusledger.android;

import android.content.ContentValues;
import android.content.Context;
import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;
import android.database.sqlite.SQLiteOpenHelper;
import org.json.JSONArray;
import org.json.JSONObject;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;

final class LedgerStore extends SQLiteOpenHelper {
    record Slice(String pkg, long start, long end) {}
    record Row(JSONObject event, int sent) {}
    record Rank(String pkg, String label, double seconds) {}
    LedgerStore(Context context) { super(context, "ledger.sqlite3", null, 1); setWriteAheadLoggingEnabled(true); }
    @Override public void onCreate(SQLiteDatabase db) {
        db.execSQL("CREATE TABLE events(id TEXT PRIMARY KEY, scope TEXT NOT NULL, payload TEXT NOT NULL, ended INTEGER NOT NULL, started INTEGER NOT NULL, pkg TEXT, label TEXT, seconds REAL NOT NULL DEFAULT 0, sent INTEGER NOT NULL DEFAULT 0)");
        db.execSQL("CREATE INDEX events_queue ON events(scope,sent,ended)");
        db.execSQL("CREATE TABLE checkpoints(scope TEXT PRIMARY KEY, payload TEXT NOT NULL)");
        db.execSQL("CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL)");
    }
    @Override public void onUpgrade(SQLiteDatabase db, int oldVersion, int newVersion) { throw new IllegalStateException("未知的缓存版本"); }

    synchronized JSONObject checkpoint(String scope) {
        try (Cursor c = getReadableDatabase().rawQuery("SELECT payload FROM checkpoints WHERE scope=?", new String[]{scope})) {
            return c.moveToFirst() ? new JSONObject(c.getString(0)) : null;
        } catch (org.json.JSONException e) { throw new IllegalStateException("采集进度损坏，请先导出诊断信息", e); }
    }
    synchronized void clearCheckpoint(String scope) { getWritableDatabase().delete("checkpoints", "scope=?", new String[]{scope}); }

    synchronized void commit(String scope, JSONObject state, List<Slice> slices, List<JSONObject> statuses, UsageReader reader) {
        SQLiteDatabase db = getWritableDatabase(); db.beginTransaction();
        try {
            for (Slice slice : slices) {
                JSONObject event = new JSONObject().put("id", eventId(scope + "|usage|" + slice.pkg + "|" + slice.start + "|" + slice.end))
                    .put("kind", "app_usage").put("app_name", reader.label(slice.pkg)).put("process_name", slice.pkg)
                    .put("started_at", iso(slice.start)).put("ended_at", iso(slice.end)).put("duration_seconds", (slice.end - slice.start) / 1000.0);
                insert(db, scope, event, slice.start, slice.end, slice.pkg, event.getString("app_name"), (slice.end - slice.start) / 1000.0);
            }
            for (JSONObject status : statuses) {
                long at = Instant.parse(status.getString("occurred_at")).toEpochMilli();
                insert(db, scope, status, at, at, null, null, 0);
            }
            if (state != null) {
                ContentValues values = new ContentValues(); values.put("scope", scope); values.put("payload", state.toString());
                db.insertWithOnConflict("checkpoints", null, values, SQLiteDatabase.CONFLICT_REPLACE);
            }
            db.setTransactionSuccessful();
        } catch (Exception e) { throw new IllegalStateException("无法保存本地记录", e); }
        finally { db.endTransaction(); }
    }
    private void insert(SQLiteDatabase db, String scope, JSONObject payload, long start, long end, String pkg, String label, double seconds) throws Exception {
        ContentValues v = new ContentValues(); v.put("id", payload.getString("id")); v.put("scope", scope); v.put("payload", payload.toString());
        v.put("started", start); v.put("ended", end); v.put("pkg", pkg); v.put("label", label); v.put("seconds", seconds);
        db.insertWithOnConflict("events", null, v, SQLiteDatabase.CONFLICT_IGNORE);
    }
    synchronized JSONArray batch(String scope, int limit) throws Exception {
        JSONArray events = new JSONArray();
        try (Cursor c = getReadableDatabase().rawQuery("SELECT payload FROM events WHERE scope=? AND sent=0 ORDER BY ended,id LIMIT ?", new String[]{scope, Integer.toString(limit)})) {
            while (c.moveToNext()) events.put(new JSONObject(c.getString(0)));
        }
        return events;
    }
    synchronized void acknowledge(String scope, JSONArray batch, JSONArray ack) throws Exception {
        java.util.Set<String> sent = new java.util.HashSet<>();
        for (int i = 0; i < batch.length(); i++) sent.add(batch.getJSONObject(i).getString("id"));
        SQLiteDatabase db = getWritableDatabase(); db.beginTransaction();
        try {
            ContentValues v = new ContentValues(); v.put("sent", 1);
            for (int i = 0; i < ack.length(); i++) if (sent.contains(ack.getString(i)))
                db.update("events", v, "scope=? AND id=? AND sent=0", new String[]{scope, ack.getString(i)});
            db.setTransactionSuccessful();
        } finally { db.endTransaction(); }
    }
    synchronized int count(String scope, boolean all) {
        try (Cursor c = getReadableDatabase().rawQuery(all ? "SELECT count(*) FROM events WHERE sent=0" : "SELECT count(*) FROM events WHERE sent=0 AND scope=?", all ? null : new String[]{scope})) { c.moveToFirst(); return c.getInt(0); }
    }
    synchronized List<Row> recent(String scope, int limit) {
        List<Row> rows = new ArrayList<>();
        try (Cursor c = getReadableDatabase().rawQuery("SELECT payload,sent FROM events WHERE scope=? ORDER BY ended DESC LIMIT ?", new String[]{scope, Integer.toString(limit)})) {
            while (c.moveToNext()) rows.add(new Row(new JSONObject(c.getString(0)), c.getInt(1)));
        } catch (Exception e) { throw new IllegalStateException("无法读取本地记录", e); }
        return rows;
    }
    synchronized List<Rank> ranking(String scope, long from, long to) {
        List<Rank> rows = new ArrayList<>();
        // rawQuery binds strings. Scalar MIN/MAX do not apply column affinity, so
        // cast the boundaries before clipping; otherwise MAX picks the text bound.
        try (Cursor c = getReadableDatabase().rawQuery("SELECT pkg,MAX(label),SUM((MIN(ended,CAST(? AS INTEGER))-MAX(started,CAST(? AS INTEGER)))/1000.0) total FROM events WHERE scope=? AND pkg IS NOT NULL AND ended>? AND started<? GROUP BY pkg ORDER BY total DESC", new String[]{""+to, ""+from, scope, ""+from, ""+to})) {
            while (c.moveToNext()) rows.add(new Rank(c.getString(0), c.getString(1), c.getDouble(2)));
        }
        return rows;
    }
    synchronized void put(String key, String value) {
        ContentValues v = new ContentValues(); v.put("key", key); v.put("value", value);
        getWritableDatabase().insertWithOnConflict("metadata", null, v, SQLiteDatabase.CONFLICT_REPLACE);
    }
    synchronized String get(String key, String fallback) {
        try (Cursor c = getReadableDatabase().rawQuery("SELECT value FROM metadata WHERE key=?", new String[]{key})) { return c.moveToFirst() ? c.getString(0) : fallback; }
    }
    synchronized void cleanup() {
        SQLiteDatabase db = getWritableDatabase(); long now = System.currentTimeMillis();
        db.delete("events", "ended<? OR (sent!=0 AND ended<?)", new String[]{""+(now-30L*86400000), ""+(now-7L*86400000)});
        db.execSQL("DELETE FROM events WHERE id IN (SELECT id FROM events ORDER BY ended DESC LIMIT -1 OFFSET 100000)");
    }
    synchronized void clearPending(String scope) { getWritableDatabase().delete("events", "scope=? AND sent=0", new String[]{scope}); }
    synchronized void quarantine(String scope, String id) {
        ContentValues v = new ContentValues(); v.put("sent", 2);
        getWritableDatabase().update("events", v, "scope=? AND id=? AND sent=0", new String[]{scope, id});
    }
    static String iso(long time) { return Instant.ofEpochMilli(time).toString(); }
    static String eventId(String identity) { return UUID.nameUUIDFromBytes(identity.getBytes(StandardCharsets.UTF_8)).toString(); }
}
