package com.focusledger.android;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.pm.ServiceInfo;
import android.net.ConnectivityManager;
import android.net.Network;
import android.os.Build;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;

public final class CollectorService extends Service {
    static final String ACTION_START = "com.focusledger.START", ACTION_RECOVER = "com.focusledger.RECOVER";
    static final String ACTION_PAUSE = "com.focusledger.PAUSE", ACTION_UPLOAD = "com.focusledger.UPLOAD", ACTION_STOP = "com.focusledger.STOP";
    static final String CHANNEL = "collection";
    private static final int NOTIFICATION_ID = 41;
    private final Handler main = new Handler(Looper.getMainLooper());
    private Agent agent;
    private boolean registered;
    private String lastNotification = "";
    private final BroadcastReceiver power = new BroadcastReceiver() {
        @Override public void onReceive(Context context, Intent intent) {
            if (Intent.ACTION_SHUTDOWN.equals(intent.getAction())) {
                if (!agent.settings.wanted()) return;
                agent.collector.execute(() -> {
                    Config c = agent.settings.get();
                    try {
                        if (agent.settings.tracking()) agent.capture(c, true);
                        if (c.configured()) agent.status(c, "shutdown", System.currentTimeMillis());
                        if (c.uploadOnShutdown) agent.uploader.request(true, true);
                    } catch (Exception e) { agent.captureNote = Agent.message(e); }
                });
            } else agent.powerEvent(intent);
        }
    };
    private final ConnectivityManager.NetworkCallback network = new ConnectivityManager.NetworkCallback() {
        @Override public void onAvailable(Network network) {
            if (agent != null && agent.settings.wanted()) agent.collector.execute(() -> {
                try { if (agent.settings.tracking()) agent.capture(agent.settings.get(), false); agent.uploader.request(false, true); }
                catch (Exception e) { agent.captureNote = Agent.message(e); }
            });
        }
    };
    @Override public void onCreate() {
        super.onCreate(); agent = Agent.get(this);
        NotificationChannel channel = new NotificationChannel(CHANNEL, "持续记录状态", NotificationManager.IMPORTANCE_LOW);
        channel.setDescription("显示采集状态，并提供暂停、上传和停止控制"); channel.setShowBadge(false); channel.setSound(null, null);
        getSystemService(NotificationManager.class).createNotificationChannel(channel);
        Notification notification = notification();
        if (Build.VERSION.SDK_INT >= 34) startForeground(NOTIFICATION_ID, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE);
        else startForeground(NOTIFICATION_ID, notification);
        IntentFilter filter = new IntentFilter();
        filter.addAction(Intent.ACTION_SCREEN_ON); filter.addAction(Intent.ACTION_SCREEN_OFF); filter.addAction(Intent.ACTION_USER_PRESENT);
        filter.addAction(Intent.ACTION_BATTERY_CHANGED); filter.addAction(Intent.ACTION_SHUTDOWN);
        if (Build.VERSION.SDK_INT >= 33) registerReceiver(power, filter, Context.RECEIVER_NOT_EXPORTED); else registerReceiver(power, filter);
        registered = true;
        getSystemService(ConnectivityManager.class).registerDefaultNetworkCallback(network);
    }
    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        if (!agent.settings.wanted()) { stopSelf(); return START_NOT_STICKY; }
        if (agent.service != this) agent.attach(this);
        String action = intent == null ? null : intent.getAction();
        if (ACTION_PAUSE.equals(action)) agent.toggleTracking();
        if (ACTION_UPLOAD.equals(action)) agent.uploader.request(true, true);
        if (ACTION_STOP.equals(action)) agent.stop();
        refreshNotification(); agent.requestTick(0); return START_STICKY;
    }
    private PendingIntent action(String action, int code) { return PendingIntent.getService(this, code, new Intent(this, CollectorService.class).setAction(action), PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE); }
    private Notification notification() {
        Config c = agent.settings.get();
        String state = !agent.settings.wanted() ? "正在停止" : !UsageReader.permitted(this) ? "等待使用情况权限" : agent.settings.tracking() ? "正在记录" : "已暂停采集";
        return new Notification.Builder(this, CHANNEL).setSmallIcon(R.drawable.ic_notification).setContentTitle("专注记录 · " + state)
            .setContentText(c.modeName() + " · 待上传 " + agent.store.count(c.scope, false) + " 条")
            .setContentIntent(PendingIntent.getActivity(this, 0, new Intent(this, MainActivity.class), PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE))
            .setOngoing(true).setOnlyAlertOnce(true).setShowWhen(false).setVisibility(Notification.VISIBILITY_PRIVATE)
            .addAction(new Notification.Action.Builder(null, agent.settings.tracking() ? "暂停" : "继续", action(ACTION_PAUSE, 1)).build())
            .addAction(new Notification.Action.Builder(null, "上传", action(ACTION_UPLOAD, 2)).build())
            .addAction(new Notification.Action.Builder(null, "停止", action(ACTION_STOP, 3)).build()).build();
    }
    void refreshNotification() {
        main.post(() -> {
            if (agent.service != this) return;
            if (!KeepAlive.notifications(this)) { lastNotification = ""; return; }
            Notification notification = notification();
            String content = notification.extras.getCharSequence(Notification.EXTRA_TITLE) + "|" + notification.extras.getCharSequence(Notification.EXTRA_TEXT);
            if (content.equals(lastNotification)) return;
            getSystemService(NotificationManager.class).notify(NOTIFICATION_ID, notification()); lastNotification = content;
        });
    }
    void stopAfterUpload() { agent.uploader.whenIdle(() -> main.post(this::stopSelf)); main.postDelayed(this::stopSelf, 12_000); }
    @Override public void onTaskRemoved(Intent rootIntent) { if (agent.settings.wanted()) KeepAlive.recoverLater(this); super.onTaskRemoved(rootIntent); }
    @Override public void onDestroy() {
        agent.detach(this); main.removeCallbacksAndMessages(null);
        if (registered) unregisterReceiver(power);
        try { getSystemService(ConnectivityManager.class).unregisterNetworkCallback(network); } catch (RuntimeException ignored) {}
        super.onDestroy();
    }
    @Override public IBinder onBind(Intent intent) { return null; }
}
