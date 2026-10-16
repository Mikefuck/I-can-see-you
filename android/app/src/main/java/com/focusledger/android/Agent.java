package com.focusledger.android;

import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.os.BatteryManager;
import android.os.SystemClock;
import org.json.JSONObject;
import java.util.ArrayList;
import java.util.List;
import java.util.Objects;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.TimeUnit;

final class Agent {
    private static Agent instance;
    static synchronized Agent get(Context context) { if (instance == null) instance = new Agent(context.getApplicationContext()); return instance; }
    final Context context;
    final Settings settings;
    final LedgerStore store;
    final UsageReader reader;
    final Transport transport;
    final Uploader uploader;
    final Management management;
    final ScheduledExecutorService collector = Executors.newSingleThreadScheduledExecutor(r -> new Thread(r, "ledger-collector"));
    final java.util.concurrent.ExecutorService io = Executors.newSingleThreadExecutor(r -> new Thread(r, "ledger-settings"));
    volatile CollectorService service;
    volatile String captureNote = "";
    private ScheduledFuture<?> tickTask;
    private long nextBattery, nextCleanup, nextCapture;
    private String lastForeground, lastPower;
    private Agent(Context context) {
        this.context = context; settings = new Settings(context); store = new LedgerStore(context);
        reader = new UsageReader(context); transport = new Transport(context); uploader = new Uploader(this); management = new Management(this);
    }
    synchronized void attach(CollectorService service) {
        this.service = service;
        if (tickTask != null) tickTask.cancel(false);
        tickTask = collector.scheduleWithFixedDelay(this::tick, 0, 1000, TimeUnit.MILLISECONDS);
        KeepAlive.schedule(context, settings.wanted());
    }
    synchronized void detach(CollectorService owner) {
        if (service != owner) return;
        service = null; if (tickTask != null) tickTask.cancel(false); tickTask = null;
    }
    private void tick() {
        if (!settings.wanted()) return;
        try {
            Config c = settings.get(); if (!c.configured()) return;
            if (settings.tracking()) {
                long elapsed = SystemClock.elapsedRealtime();
                if (reader.screen() || elapsed >= nextCapture) {
                    capture(c, false); nextCapture = elapsed + (c.mode.equals("xiaomi") ? 60_000 : 30_000);
                }
                if (c.batteryEnabled && elapsed >= nextBattery) { status(c, "periodic", System.currentTimeMillis()); nextBattery = elapsed + c.batterySeconds * 1000L; }
                String foreground = foreground(c).optJSONObject("app") == null ? "" : foreground(c).getJSONObject("app").optString("process_name");
                if (!Objects.equals(lastForeground, foreground)) {
                    lastForeground = foreground; if (c.uploadOnChange) uploader.request(false, true); updateNotification();
                }
            }
            uploader.request(false, false);
            if (SystemClock.elapsedRealtime() >= nextCleanup) { store.cleanup(); nextCleanup = SystemClock.elapsedRealtime() + 3600000; }
        } catch (Exception e) { captureNote = message(e); }
    }
    void capture(Config c, boolean stop) {
        if (!UsageReader.permitted(context)) {
            JSONObject known = store.checkpoint(c.scope);
            if (known != null) {
                List<LedgerStore.Slice> tail = new ArrayList<>(); UsageReducer previous = new UsageReducer(known, (p,s,e) -> tail.add(new LedgerStore.Slice(p,s,e)));
                previous.stop(previous.cursor); store.commit(c.scope, previous.json(), tail, java.util.Collections.emptyList(), reader); store.clearCheckpoint(c.scope);
            }
            captureNote = "使用情况访问权限已关闭，采集暂停；恢复授权后从当前时间继续。"; return;
        }
        long now = System.currentTimeMillis(); JSONObject saved = store.checkpoint(c.scope);
        int boot = android.provider.Settings.Global.getInt(context.getContentResolver(), android.provider.Settings.Global.BOOT_COUNT, 0);
        boolean reset = saved != null && (saved.optLong("cursor") > now || (saved.optInt("boot", boot) == boot && saved.has("elapsed")
            && Math.abs((now - saved.optLong("cursor")) - (SystemClock.elapsedRealtime() - saved.optLong("elapsed"))) > 60_000));
        if (reset) { saved = null; captureNote = "检测到手机时间变化，已丢弃无法确定的在途片段；请开启自动日期时间。"; store.put("recovery_note", captureNote); }
        if (saved != null && now - saved.optLong("cursor") > 48L * 3600000) {
            saved = new UsageReducer(now - 48L * 3600000, false, false, (p,s,e) -> {}).json();
            store.put("recovery_note", "中断超过 48 小时，仅尝试恢复最近 48 小时；系统未提供的片段不推算。");
        }
        long cursor = saved == null ? now : saved.optLong("cursor");
        boolean first = saved == null;
        do {
            List<LedgerStore.Slice> slices = new ArrayList<>(); List<JSONObject> statuses = new ArrayList<>();
            UsageReducer.Sink sink = (pkg, start, end) -> slices.add(new LedgerStore.Slice(pkg, start, end));
            UsageReducer reducer = saved == null ? reader.seed(now, sink) : new UsageReducer(saved, sink);
            long end = Math.min(now, cursor + 15 * 60_000L);
            if (!first) for (UsageReader.Point p : reader.query(cursor, end)) {
                reducer.event(p.type(), p.pkg(), p.at());
                String reason = switch (p.type()) { case UsageReducer.SCREEN_OFF -> "suspend"; case UsageReducer.UNLOCKED -> "resume"; case UsageReducer.SHUTDOWN -> "shutdown"; default -> null; };
                if (reason != null) statuses.add(statusEvent(c, reason, p.at(), Math.abs(now-p.at()) < 10_000));
            }
            reducer.advance(end);
            if (end == now) {
                reducer.reconcile(reader.screen(), reader.unlocked(), now);
                if (stop) reducer.stop(now);
            }
            JSONObject state = reducer.json(); if (end == now) statePut(state, "elapsed", SystemClock.elapsedRealtime()); statePut(state, "boot", boot);
            store.commit(c.scope, state, slices, statuses, reader); saved = state; cursor = end; first = false;
        } while (cursor < now);
        if (!reset) captureNote = "";
        store.put("last_capture", ""+now);
        String bootKey = c.scope + ":boot";
        if (!Integer.toString(boot).equals(store.get(bootKey, ""))) { status(c, "startup", now); store.put(bootKey, ""+boot); }
    }
    private static void statePut(JSONObject object, String key, Object value) { try { object.put(key, value); } catch (Exception e) { throw new IllegalStateException(e); } }
    JSONObject foreground(Config c) {
        long now = System.currentTimeMillis(); JSONObject state = store.checkpoint(c.scope);
        String pkg = null; long since = now;
        if (!settings.tracking() && c.scope.equals(settings.get().scope)) since = Math.min(now, settings.prefs.getLong("idle_since", now));
        if (settings.tracking() && c.scope.equals(settings.get().scope) && UsageReader.permitted(context) && state != null
            && now >= state.optLong("cursor") && now - state.optLong("cursor") < 10_000 && reader.screen() && reader.unlocked()) {
            UsageReducer reducer = new UsageReducer(state, (p,s,e) -> {}); pkg = reducer.active(); since = Math.min(now, reducer.activeSince);
        }
        try {
            return new JSONObject().put("observed_at", LedgerStore.iso(now)).put("since", LedgerStore.iso(since))
                .put("app", pkg == null ? JSONObject.NULL : new JSONObject().put("app_name", reader.label(pkg)).put("process_name", pkg));
        } catch (Exception e) { throw new IllegalStateException(e); }
    }
    private JSONObject statusEvent(Config c, String reason, long at, boolean readBattery) {
        try {
            JSONObject event = new JSONObject().put("id", LedgerStore.eventId(c.scope + "|status|" + reason + "|" + at))
                .put("kind", "device_status").put("occurred_at", LedgerStore.iso(at)).put("reason", reason)
                .put("battery_percent", JSONObject.NULL).put("charging", JSONObject.NULL).put("ac_online", JSONObject.NULL).put("battery_life_seconds", JSONObject.NULL);
            if (readBattery && c.batteryEnabled) {
                Intent battery = context.registerReceiver(null, new IntentFilter(Intent.ACTION_BATTERY_CHANGED));
                if (battery != null && battery.getBooleanExtra(BatteryManager.EXTRA_PRESENT, true)) {
                    int level = battery.getIntExtra(BatteryManager.EXTRA_LEVEL, -1), scale = battery.getIntExtra(BatteryManager.EXTRA_SCALE, -1);
                    int state = battery.getIntExtra(BatteryManager.EXTRA_STATUS, -1);
                    if (level >= 0 && scale > 0) event.put("battery_percent", Math.max(0, Math.min(100, level*100/scale)));
                    event.put("charging", state == BatteryManager.BATTERY_STATUS_CHARGING || state == BatteryManager.BATTERY_STATUS_FULL)
                        .put("ac_online", battery.getIntExtra(BatteryManager.EXTRA_PLUGGED, 0) != 0);
                }
            }
            return event;
        } catch (Exception e) { throw new IllegalStateException(e); }
    }
    void status(Config c, String reason, long at) { store.commit(c.scope, null, java.util.Collections.emptyList(), java.util.Collections.singletonList(statusEvent(c, reason, at, true)), reader); }
    void powerEvent(Intent intent) {
        String action = intent.getAction();
        collector.execute(() -> {
            if (!settings.wanted() || !settings.tracking()) return;
            Config c = settings.get();
            try {
                if (Intent.ACTION_BATTERY_CHANGED.equals(action)) {
                    String current = intent.getIntExtra(BatteryManager.EXTRA_PLUGGED, 0) + ":" + intent.getIntExtra(BatteryManager.EXTRA_STATUS, 0);
                    if (lastPower != null && !current.equals(lastPower) && c.batteryEnabled) status(c, "periodic", System.currentTimeMillis());
                    lastPower = current;
                } else {
                    capture(c, false);
                    if ((Intent.ACTION_SCREEN_OFF.equals(action) && c.uploadOnSuspend) || Intent.ACTION_USER_PRESENT.equals(action)) uploader.request(false, true);
                }
            } catch (Exception e) { captureNote = message(e); }
        });
    }
    void toggleTracking() {
        collector.execute(() -> {
            Config c = settings.get();
            try {
                if (settings.tracking()) { try { capture(c, true); } finally { settings.intent(true, false); store.clearCheckpoint(c.scope); } }
                else { store.clearCheckpoint(c.scope); settings.intent(true, true); nextBattery = 0; capture(c, false); }
                uploader.request(false, true);
            } catch (Exception e) { captureNote = message(e); }
            updateNotification();
        });
    }
    void stop() {
        collector.execute(() -> {
            Config c = settings.get();
            try { if (settings.tracking()) capture(c, true); } catch (Exception e) { captureNote = message(e); }
            finally {
                settings.intent(false, false); store.clearCheckpoint(c.scope); KeepAlive.schedule(context, false);
                uploader.request(true, true);
                CollectorService owner = service; if (owner != null) owner.stopAfterUpload();
            }
        });
    }
    void begin() {
        collector.execute(() -> {
            if (!settings.get().configured()) { captureNote = "请先保存并验证服务器连接"; return; }
            if (!UsageReader.permitted(context)) { captureNote = "请先开启使用情况访问权限"; return; }
            if (!settings.tracking()) store.clearCheckpoint(settings.get().scope);
            settings.intent(true, true); KeepAlive.schedule(context, true); KeepAlive.start(context, CollectorService.ACTION_START);
        });
    }
    void saveConfig(Config checked, Runnable done, java.util.function.Consumer<String> error) {
        collector.execute(() -> {
            try {
                Config previous = settings.get();
                if (settings.tracking() && previous.configured()) { capture(previous, true); store.clearCheckpoint(previous.scope); }
                settings.save(checked); lastForeground = null; nextBattery = 0;
                if (settings.tracking()) capture(checked, false);
                KeepAlive.schedule(context, settings.wanted());
                if (settings.wanted()) uploader.request(true, true);
                done.run(); updateNotification();
            } catch (Exception e) { error.accept(message(e)); }
        });
    }
    void recover(Runnable done) {
        collector.execute(() -> {
            try {
                Config c = settings.get();
                if (!settings.wanted() || !c.configured()) { done.run(); return; }
                if (settings.tracking()) capture(c, false);
                if (service == null && KeepAlive.batteryExempt(context)) KeepAlive.start(context, CollectorService.ACTION_RECOVER);
                uploader.request(true, true); uploader.whenIdle(done);
            } catch (Exception e) { captureNote = message(e); done.run(); }
        });
    }
    void updateNotification() { CollectorService owner = service; if (owner != null) owner.refreshNotification(); }
    static String message(Exception e) { return e.getMessage() == null ? "操作未完成，请稍后重试" : e.getMessage(); }
}
