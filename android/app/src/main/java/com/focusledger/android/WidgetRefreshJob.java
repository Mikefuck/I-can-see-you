package com.focusledger.android;

import android.app.job.JobInfo;
import android.app.job.JobParameters;
import android.app.job.JobScheduler;
import android.app.job.JobService;
import android.content.ComponentName;
import android.content.Context;
import org.json.JSONObject;
import java.time.ZoneId;
import java.util.HashMap;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.ConcurrentHashMap;

/** Independent of usage collection: no foreground service or exact alarms for a home-screen card. */
public final class WidgetRefreshJob extends JobService {
    private static final int PERIODIC = 7412, IMMEDIATE = 7413;
    private static final ExecutorService WORKER = Executors.newSingleThreadExecutor(r -> new Thread(r, "ledger-widget"));
    private static final class Running { volatile boolean stopped; Future<?> future; }
    private final Map<Integer, Running> running = new ConcurrentHashMap<>();
    static void schedule(Context c) {
        if (UsageWidgetProvider.ids(c).length == 0) return;
        JobScheduler scheduler = c.getSystemService(JobScheduler.class);
        if (scheduler.getPendingJob(PERIODIC) == null) scheduler.schedule(new JobInfo.Builder(PERIODIC, new ComponentName(c, WidgetRefreshJob.class))
            .setPeriodic(15 * 60000L).setRequiredNetworkType(JobInfo.NETWORK_TYPE_ANY).setPersisted(true).build());
    }
    static void request(Context c) {
        if (UsageWidgetProvider.ids(c).length == 0) return;
        c.getSystemService(JobScheduler.class).schedule(new JobInfo.Builder(IMMEDIATE, new ComponentName(c, WidgetRefreshJob.class))
            .setOverrideDeadline(0).build());
    }
    static void cancel(Context c) { JobScheduler j = c.getSystemService(JobScheduler.class); j.cancel(PERIODIC); j.cancel(IMMEDIATE); }
    static void revokeLater(Context c, WidgetStore.Options o) {
        // Best effort on deletion. Offline grants remain revocable from the website's account page.
        WORKER.execute(() -> { try { new WidgetNetwork().revoke(o); } catch (Exception ignored) {} });
    }
    @Override public boolean onStartJob(JobParameters params) {
        Running state = new Running(); running.put(params.getJobId(), state);
        state.future = WORKER.submit(() -> {
            try { refresh(getApplicationContext()); }
            finally { if (running.remove(params.getJobId(), state) && !state.stopped) jobFinished(params, false); }
        });
        return true;
    }
    void refresh(Context context) {
        WidgetStore store = new WidgetStore(context); WidgetNetwork network = new WidgetNetwork();
        Map<String, JSONObject> loaded = new HashMap<>(); Map<String, Exception> failures = new HashMap<>();
        for (int id : UsageWidgetProvider.ids(context)) {
            if (Thread.currentThread().isInterrupted()) return;
            WidgetStore.Options o = store.options(id); if (!o.configured) continue;
            String identity = o.identity();
            try {
                if (o.mode.equals("members") && (o.token.isEmpty() || o.expires <= System.currentTimeMillis() / 1000d)) {
                    store.failure(id, identity, "授权已失效 · 点击设置重新授权", true); continue;
                }
                if (failures.containsKey(identity)) throw failures.get(identity);
                JSONObject data = loaded.get(identity);
                if (data == null) {
                    try { data = network.fetch(o); WidgetData.parse(data, ZoneId.systemDefault()); loaded.put(identity, data); }
                    catch (Exception e) { failures.put(identity, e); throw e; }
                }
                store.success(id, identity, data);
            } catch (Exception e) {
                boolean denied = e instanceof Transport.ApiError api && (api.status == 401 || api.status == 403);
                store.failure(id, identity, WidgetNetwork.message(e), denied);
            } finally { if (UsageWidgetProvider.owns(context, id)) UsageWidgetProvider.render(context, id); }
        }
    }
    @Override public boolean onStopJob(JobParameters params) {
        Running state = running.remove(params.getJobId());
        if (state != null) { state.stopped = true; if (state.future != null) state.future.cancel(true); }
        return true;
    }
}
