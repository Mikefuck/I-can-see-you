package com.focusledger.android;

import android.os.SystemClock;
import org.json.JSONArray;
import org.json.JSONObject;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicBoolean;

final class Uploader {
    private final Agent agent;
    private final ExecutorService executor = Executors.newSingleThreadExecutor(r -> new Thread(r, "ledger-upload"));
    private final AtomicBoolean busy = new AtomicBoolean();
    private volatile long retryAfter, regularAfter;
    private volatile boolean pending;
    private int failures;
    private final java.util.concurrent.ConcurrentLinkedQueue<Runnable> callbacks = new java.util.concurrent.ConcurrentLinkedQueue<>();
    Uploader(Agent agent) { this.agent = agent; }
    boolean busy() { return busy.get(); }
    void whenIdle(Runnable callback) { callbacks.add(callback); if (!busy.get()) finishCallbacks(); }
    private void finishCallbacks() { Runnable callback; while ((callback = callbacks.poll()) != null) callback.run(); }
    void request(boolean manual, boolean immediate) {
        long now = SystemClock.elapsedRealtime();
        if (!manual && (now < retryAfter || (!immediate && now < regularAfter))) return;
        if (!busy.compareAndSet(false, true)) { if (manual || immediate) pending = true; return; }
        executor.execute(() -> {
            Config c = agent.settings.get();
            try {
                if (!c.configured()) return;
                syncMetadata(c);
                int limit = 500;
                for (int pass = 0; pass < 8; pass++) {
                    JSONArray events = agent.store.batch(c.scope, limit);
                    JSONObject body = new JSONObject().put("schema_version", 1).put("device", c.device()).put("events", events);
                    if (c.features.contains("foreground")) body.put("foreground", agent.foreground(c));
                    Transport.Reply reply;
                    try { reply = agent.transport.request(c, "POST", "/api/v1/usage/batches", body); }
                    catch (Transport.ApiError e) {
                        if (e.status == 413 && events.length() > 1) { limit = Math.max(1, events.length()/2); pass--; continue; }
                        if (e.status == 422 && quarantine(c, events, e.response)) continue;
                        throw e;
                    }
                    JSONArray ack = reply.json().optJSONArray("acknowledged_ids");
                    if (ack == null) throw new IllegalStateException("服务器没有返回记录确认列表，队列已保留");
                    agent.store.acknowledge(c.scope, events, ack);
                    if (events.length() > 0 && ack.length() == 0) throw new IllegalStateException("服务器尚未确认这些记录，队列已保留");
                    agent.store.put(c.scope + ":last_upload", ""+System.currentTimeMillis());
                    agent.store.put(c.scope + ":last_endpoint", reply.endpoint());
                    agent.store.put(c.scope + ":last_error", "");
                    if (events.length() < limit) break;
                }
                failures = 0; retryAfter = 0; regularAfter = SystemClock.elapsedRealtime() + c.uploadSeconds * 1000L;
            } catch (Exception e) {
                failures = Math.min(failures + 1, 6);
                retryAfter = SystemClock.elapsedRealtime() + Math.min(300_000L, 5000L * (1L << (failures-1)));
                agent.store.put(c.scope + ":last_error", Agent.message(e));
            } finally {
                busy.set(false); agent.updateNotification();
                boolean again = pending; pending = false; if (again) request(false, true);
                if (!busy.get()) finishCallbacks();
            }
        });
    }
    private void syncMetadata(Config c) throws Exception {
        String digest = Config.sha256(c.aliases.toString() + "|" + c.colors);
        if (digest.equals(agent.store.get(c.scope + ":metadata_hash", ""))) return;
        boolean supported = true;
        if (c.features.contains("app_aliases")) agent.transport.request(c, "PUT", "/api/v1/agent/app-aliases", new JSONObject().put("device", c.device()).put("app_aliases", c.aliases));
        else if (c.aliases.length() > 0) supported = false;
        if (c.features.contains("app_colors")) agent.transport.request(c, "PUT", "/api/v1/agent/app-colors", new JSONObject().put("device", c.device()).put("app_colors", c.colors));
        else if (c.colors.length() > 0) supported = false;
        agent.store.put(c.scope + ":metadata_hash", digest);
        agent.store.put(c.scope + ":metadata_note", supported ? "" : "服务端版本不支持部分名称或颜色同步，请升级服务端。");
    }
    private boolean quarantine(Config c, JSONArray batch, JSONObject error) throws Exception {
        JSONArray details = error.optJSONArray("detail"); if (details == null) return false;
        java.util.Set<Integer> indexes = new java.util.HashSet<>();
        for (int i = 0; i < details.length(); i++) {
            JSONArray loc = details.getJSONObject(i).optJSONArray("loc");
            if (loc != null && loc.length() > 2 && "body".equals(loc.optString(0)) && "events".equals(loc.optString(1)) && loc.opt(2) instanceof Number) {
                int index = loc.getInt(2); if (index >= 0 && index < batch.length()) indexes.add(index);
            }
        }
        for (int index : indexes) agent.store.quarantine(c.scope, batch.getJSONObject(index).getString("id"));
        if (!indexes.isEmpty()) agent.store.put(c.scope + ":validation_note", "有 " + indexes.size() + " 条记录未通过服务端校验，已单独保留，请检查手机时间或导出诊断。");
        return !indexes.isEmpty();
    }
}
