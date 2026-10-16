package com.focusledger.android;

import android.app.Activity;
import android.app.AlertDialog;
import android.app.job.JobInfo;
import android.app.job.JobScheduler;
import android.app.NotificationManager;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.net.Uri;
import android.os.Build;
import android.os.PowerManager;
import android.provider.Settings;
import java.util.Locale;

final class KeepAlive {
    static final int PERIODIC_JOB = 4101, RECOVERY_JOB = 4102;
    static boolean isXiaomi() {
        String value = (Build.MANUFACTURER + " " + Build.BRAND).toLowerCase(Locale.ROOT);
        return value.contains("xiaomi") || value.contains("redmi") || value.contains("poco");
    }
    static boolean batteryExempt(Context c) { return c.getSystemService(PowerManager.class).isIgnoringBatteryOptimizations(c.getPackageName()); }
    static boolean notifications(Context c) {
        NotificationManager manager = c.getSystemService(NotificationManager.class);
        android.app.NotificationChannel channel = manager.getNotificationChannel(CollectorService.CHANNEL);
        return manager.areNotificationsEnabled() && (channel == null || channel.getImportance() != NotificationManager.IMPORTANCE_NONE);
    }
    static void schedule(Context context, boolean enabled) {
        JobScheduler jobs = context.getSystemService(JobScheduler.class);
        if (!enabled) { jobs.cancel(PERIODIC_JOB); jobs.cancel(RECOVERY_JOB); return; }
        jobs.schedule(new JobInfo.Builder(PERIODIC_JOB, new ComponentName(context, RecoveryJob.class))
            .setPeriodic(15 * 60_000L, 5 * 60_000L).setPersisted(Agent.get(context).settings.get().bootEnabled).setBackoffCriteria(60_000, JobInfo.BACKOFF_POLICY_EXPONENTIAL).build());
    }
    static void recoverLater(Context c) {
        c.getSystemService(JobScheduler.class).schedule(new JobInfo.Builder(RECOVERY_JOB, new ComponentName(c, RecoveryJob.class))
            .setMinimumLatency(30_000).setBackoffCriteria(60_000, JobInfo.BACKOFF_POLICY_EXPONENTIAL).build());
    }
    static boolean start(Context c, String action) {
        try { c.startForegroundService(new Intent(c, CollectorService.class).setAction(action)); return true; }
        catch (RuntimeException e) {
            Agent.get(c).store.put("recovery_note", "系统暂不允许从后台启动，记录将在允许时补采；也可以打开 App 恢复。");
            recoverLater(c); return false;
        }
    }
    static void usageSettings(Activity a) {
        open(a, new Intent(Settings.ACTION_USAGE_ACCESS_SETTINGS).setData(Uri.parse("package:" + a.getPackageName())),
            new Intent(Settings.ACTION_USAGE_ACCESS_SETTINGS));
    }
    static void batterySettings(Activity a) {
        open(a, new Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS).setData(Uri.parse("package:" + a.getPackageName())),
            new Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS));
    }
    static void appInfo(Activity a) { open(a, new Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS).setData(Uri.parse("package:" + a.getPackageName())), new Intent(Settings.ACTION_SETTINGS)); }
    static void notificationSettings(Activity a) {
        Intent app = new Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS).putExtra(Settings.EXTRA_APP_PACKAGE, a.getPackageName());
        if (a.getSystemService(NotificationManager.class).getNotificationChannel(CollectorService.CHANNEL) == null) open(a, app, new Intent(Settings.ACTION_SETTINGS));
        else open(a, new Intent(Settings.ACTION_CHANNEL_NOTIFICATION_SETTINGS).putExtra(Settings.EXTRA_APP_PACKAGE, a.getPackageName())
            .putExtra(Settings.EXTRA_CHANNEL_ID, CollectorService.CHANNEL), app);
    }
    static void xiaomiAutostart(Activity a) {
        if (!isXiaomi()) { appInfo(a); return; }
        Intent target = new Intent().setComponent(new ComponentName("com.miui.securitycenter", "com.miui.permcenter.autostart.AutoStartManagementActivity"));
        if (!tryOpen(a, target)) {
            new AlertDialog.Builder(a).setTitle("打开自启动设置").setMessage("此系统版本未提供可打开的专用入口。请在设置中搜索“自启动”，允许专注记录自启动。")
                .setPositiveButton("打开应用信息", (d,w) -> appInfo(a)).setNegativeButton("知道了", null).show();
        }
    }
    static void xiaomiBattery(Activity a) {
        if (!isXiaomi()) { appInfo(a); return; }
        Intent target = new Intent().setComponent(new ComponentName("com.miui.powerkeeper", "com.miui.powerkeeper.ui.HiddenAppsConfigActivity"))
            .putExtra("package_name", a.getPackageName()).putExtra("package_label", "专注记录");
        open(a, target, new Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS).setData(Uri.parse("package:" + a.getPackageName())));
    }
    static void xiaomiLock(Activity a) {
        new AlertDialog.Builder(a).setTitle("将专注记录加入后台锁定").setMessage("打开手机管家 → 右上角设置 → 垃圾清理或优化加速 → 锁定应用，将“专注记录”锁定。部分版本也支持在最近任务中长按应用卡片后点锁形按钮。\n\n后台锁定主要防止一键清理，不保证系统在内存不足时一定保留进程。菜单名称以手机实际显示为准。")
            .setPositiveButton("打开手机管家", (d,w) -> {
                Intent launch = a.getPackageManager().getLaunchIntentForPackage("com.miui.securitycenter");
                if (launch == null || !tryOpen(a, launch)) appInfo(a);
            }).setNegativeButton("关闭", null).show();
    }
    private static void open(Activity a, Intent preferred, Intent fallback) { if (!tryOpen(a, preferred) && !tryOpen(a, fallback)) appInfoLast(a); }
    private static void appInfoLast(Activity a) { new AlertDialog.Builder(a).setMessage("系统未提供此设置入口，请从手机设置中手动查找。").setPositiveButton("知道了", null).show(); }
    private static boolean tryOpen(Activity a, Intent intent) {
        try { a.startActivity(intent); return true; } catch (RuntimeException e) { return false; }
    }
}
