package com.focusledger.android;

import android.appwidget.AppWidgetManager;
import android.appwidget.AppWidgetProvider;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.os.Build;
import android.os.Bundle;
import android.util.SizeF;
import android.widget.RemoteViews;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** Standard Android AppWidget only: no Xiaomi metadata, private broadcasts or separate process. */
public final class UsageWidgetProvider extends AppWidgetProvider {
    static final String REFRESH = "com.focusledger.android.widget.REFRESH", PAGE = "com.focusledger.android.widget.PAGE";
    static int[] ids(Context c) { return AppWidgetManager.getInstance(c).getAppWidgetIds(new ComponentName(c, UsageWidgetProvider.class)); }
    static boolean owns(Context c, int id) { for (int own : ids(c)) if (id == own) return true; return false; }
    @Override public void onUpdate(Context c, AppWidgetManager manager, int[] ids) {
        for (int id : ids) render(c, id);
        WidgetRefreshJob.schedule(c); WidgetRefreshJob.request(c);
    }
    @Override public void onEnabled(Context c) { WidgetRefreshJob.schedule(c); }
    @Override public void onDisabled(Context c) { WidgetRefreshJob.cancel(c); }
    @Override public void onDeleted(Context c, int[] ids) {
        WidgetStore store = new WidgetStore(c);
        for (int id : ids) {
            WidgetStore.Options old = store.options(id); store.delete(id);
            if (!old.token.isEmpty()) WidgetRefreshJob.revokeLater(c, old);
        }
    }
    @Override public void onAppWidgetOptionsChanged(Context c, AppWidgetManager m, int id, Bundle options) { render(c, id); }
    @Override public void onRestored(Context c, int[] oldIds, int[] newIds) {
        // Credentials and cached member data are deliberately excluded from backup.
        WidgetStore store = new WidgetStore(c); for (int id : oldIds) store.delete(id);
        for (int id : newIds) render(c, id);
    }
    @Override public void onReceive(Context c, Intent intent) {
        String action = intent.getAction();
        if (REFRESH.equals(action) || PAGE.equals(action)) {
            int id = intent.getIntExtra(AppWidgetManager.EXTRA_APPWIDGET_ID, AppWidgetManager.INVALID_APPWIDGET_ID);
            if (!owns(c, id)) return;
            if (PAGE.equals(action)) new WidgetStore(c).page(id, Math.max(0, intent.getIntExtra("page", 0)));
            render(c, id);
            if (REFRESH.equals(action)) WidgetRefreshJob.request(c);
            return;
        }
        if (Intent.ACTION_TIME_CHANGED.equals(action) || Intent.ACTION_TIMEZONE_CHANGED.equals(action) || Intent.ACTION_DATE_CHANGED.equals(action)
                || Intent.ACTION_LOCALE_CHANGED.equals(action) || Intent.ACTION_CONFIGURATION_CHANGED.equals(action)) {
            renderAll(c); WidgetRefreshJob.request(c); return;
        }
        super.onReceive(c, intent);
    }
    static void renderAll(Context c) { for (int id : ids(c)) render(c, id); }
    static void render(Context c, int id) {
        AppWidgetManager manager = AppWidgetManager.getInstance(c); Bundle options = manager.getAppWidgetOptions(id);
        if (Build.VERSION.SDK_INT >= 31) {
            List<SizeF> sizes = options.getParcelableArrayList(AppWidgetManager.OPTION_APPWIDGET_SIZES);
            if (sizes != null && !sizes.isEmpty()) {
                Map<SizeF, RemoteViews> layouts = new LinkedHashMap<>();
                for (SizeF size : sizes) {
                    if (size.getWidth() > 0 && size.getHeight() > 0 && layouts.size() < 8)
                        layouts.put(size, WidgetRenderer.render(c, id, size.getWidth(), size.getHeight()));
                }
                if (!layouts.isEmpty()) { manager.updateAppWidget(id, new RemoteViews(layouts)); return; }
            }
        }
        int width = options.getInt(AppWidgetManager.OPTION_APPWIDGET_MIN_WIDTH, 300), height = options.getInt(AppWidgetManager.OPTION_APPWIDGET_MAX_HEIGHT, 160);
        int wide = options.getInt(AppWidgetManager.OPTION_APPWIDGET_MAX_WIDTH, width), shortHeight = options.getInt(AppWidgetManager.OPTION_APPWIDGET_MIN_HEIGHT, height);
        RemoteViews portrait = WidgetRenderer.render(c, id, Math.max(110, width), Math.max(110, height));
        RemoteViews landscape = WidgetRenderer.render(c, id, Math.max(110, wide), Math.max(110, shortHeight));
        manager.updateAppWidget(id, new RemoteViews(landscape, portrait));
    }
}
