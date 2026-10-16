package com.focusledger.android;

import android.app.AppOpsManager;
import android.app.KeyguardManager;
import android.app.usage.UsageEvents;
import android.app.usage.UsageStatsManager;
import android.content.Context;
import android.os.Build;
import android.os.PowerManager;
import android.os.UserManager;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

final class UsageReader {
    record Point(long at, int type, String pkg) {}
    private final Context context;
    private final Map<String, String> labels = new HashMap<>();
    UsageReader(Context context) { this.context = context; }
    static boolean permitted(Context context) {
        AppOpsManager ops = context.getSystemService(AppOpsManager.class);
        int mode = Build.VERSION.SDK_INT >= 29
            ? ops.unsafeCheckOpNoThrow(AppOpsManager.OPSTR_GET_USAGE_STATS, android.os.Process.myUid(), context.getPackageName())
            : ops.checkOpNoThrow(AppOpsManager.OPSTR_GET_USAGE_STATS, android.os.Process.myUid(), context.getPackageName());
        return mode == AppOpsManager.MODE_ALLOWED;
    }
    boolean screen() { return context.getSystemService(PowerManager.class).isInteractive(); }
    boolean unlocked() { return !context.getSystemService(KeyguardManager.class).isKeyguardLocked(); }
    List<Point> query(long from, long to) {
        if (!permitted(context)) throw new IllegalStateException("请授予使用情况访问权限");
        if (!context.getSystemService(UserManager.class).isUserUnlocked()) throw new IllegalStateException("重启后请先解锁手机，才能读取使用记录");
        UsageEvents events = context.getSystemService(UsageStatsManager.class).queryEvents(from, to);
        if (events == null) throw new IllegalStateException("系统暂未提供使用记录，将稍后重试");
        List<Point> result = new ArrayList<>(); UsageEvents.Event e = new UsageEvents.Event();
        while (events.hasNextEvent()) {
            events.getNextEvent(e); int type = e.getEventType();
            if (type == 1 || type == 2 || (type >= 15 && type <= 18) || type == 26 || type == 27)
                result.add(new Point(e.getTimeStamp(), type, e.getPackageName()));
        }
        return result;
    }
    UsageReducer seed(long at, UsageReducer.Sink sink) {
        long from = Math.max(0, at - 6L * 3600000);
        UsageReducer seed = new UsageReducer(from, true, true, (pkg, start, end) -> {});
        for (Point p : query(from, at)) seed.event(p.type, p.pkg, p.at);
        seed.startHere(at, screen(), unlocked());
        return new UsageReducer(seed.json(), sink);
    }
    synchronized String label(String pkg) {
        if (pkg == null || pkg.isEmpty()) return "未知应用";
        if (labels.containsKey(pkg)) return labels.get(pkg);
        String value;
        try { value = context.getPackageManager().getApplicationLabel(context.getPackageManager().getApplicationInfo(pkg, 0)).toString().trim(); }
        catch (Exception e) { value = pkg; }
        if (value.isEmpty()) value = pkg; if (value.length() > 200) value = value.substring(0, 200);
        if (labels.size() > 1000) labels.clear(); labels.put(pkg, value); return value;
    }
}
