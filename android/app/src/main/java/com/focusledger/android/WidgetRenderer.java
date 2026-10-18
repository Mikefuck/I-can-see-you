package com.focusledger.android;

import android.app.PendingIntent;
import android.appwidget.AppWidgetManager;
import android.content.Context;
import android.content.Intent;
import android.content.res.Configuration;
import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.net.Uri;
import android.util.TypedValue;
import android.view.View;
import android.widget.RemoteViews;
import java.time.Instant;
import java.time.ZoneId;
import java.time.format.DateTimeFormatter;
import java.util.Collections;
import java.util.List;

/** Text and interactions remain native RemoteViews. Only the coloured time strips are bitmaps. */
final class WidgetRenderer {
    record Metrics(int padding, boolean narrow, boolean status, boolean summary, boolean axis, int capacity) {}
    static Metrics metrics(float width, float height, float fontScale) {
        boolean narrow = width < 220, status = !narrow && height >= 240, summary = !narrow && height >= 260;
        boolean axis = !narrow && height >= 135;
        int padding = narrow ? 6 : height < 200 ? 8 : 12;
        float reserved = padding * 2 + Math.max(20, 18 * fontScale) + 28 + (axis ? 16 : 0) + (summary ? 20 : 0);
        float row = 16 + Math.max(18, (narrow ? 14 : 15) * fontScale) + (status ? Math.max(16, 13 * fontScale) : 0) + (narrow ? 12 * fontScale : 0);
        int capacity = Math.max(1, Math.min(12, (int)((height - reserved) / row)));
        return new Metrics(padding, narrow, status, summary, axis, capacity);
    }
    record Colors(int paper, int ink, int muted, int rule, int red) {
        Colors(boolean dark) { this(color(dark ? "#282925" : "#f6f1df"), color(dark ? "#e6e3d5" : "#30312c"),
            color(dark ? "#bab9ac" : "#66675c"), color(dark ? "#4b4d43" : "#d7d1bd"), color(dark ? "#ff6b61" : "#eb0000")); }
    }
    static boolean dark(Context c, String theme) {
        return theme.equals("dark") || theme.equals("system") && (c.getResources().getConfiguration().uiMode & Configuration.UI_MODE_NIGHT_MASK) == Configuration.UI_MODE_NIGHT_YES;
    }
    static RemoteViews render(Context context, int id, float width, float height) {
        WidgetStore store = new WidgetStore(context); WidgetStore.Options o = store.options(id);
        boolean dark = dark(context, o.theme); Colors colors = new Colors(dark);
        float font = context.getResources().getConfiguration().fontScale;
        Metrics m = metrics(width, height, font); ZoneId zone = ZoneId.systemDefault();
        RemoteViews v = new RemoteViews(context.getPackageName(), R.layout.widget_timetable);
        v.setInt(android.R.id.background, "setBackgroundResource", dark ? R.drawable.widget_background_dark : R.drawable.widget_background_light);
        v.setViewPadding(android.R.id.background, dp(context, m.padding), dp(context, m.padding), dp(context, m.padding), dp(context, m.padding));
        for (int view : new int[]{R.id.widget_title, R.id.widget_previous, R.id.widget_next}) v.setTextColor(view, colors.ink);
        for (int view : new int[]{R.id.widget_date, R.id.widget_summary, R.id.widget_refresh, R.id.widget_page, R.id.widget_empty}) v.setTextColor(view, colors.muted);
        v.setTextColor(R.id.widget_settings, colors.red);
        v.setViewVisibility(R.id.widget_date, m.narrow ? View.GONE : View.VISIBLE);
        v.setViewVisibility(R.id.widget_summary, m.summary ? View.VISIBLE : View.GONE);
        v.setViewVisibility(R.id.widget_axis, View.GONE);
        v.setViewVisibility(R.id.widget_settings, m.narrow ? View.GONE : View.VISIBLE);
        v.setOnClickPendingIntent(R.id.widget_heading, settings(context, id));
        v.setOnClickPendingIntent(R.id.widget_empty, settings(context, id));
        v.setOnClickPendingIntent(R.id.widget_settings, settings(context, id));
        v.setOnClickPendingIntent(R.id.widget_refresh, action(context, id, UsageWidgetProvider.REFRESH, 0));
        WidgetData data = null;
        try { if (store.data(id) != null) data = WidgetData.parse(store.data(id), zone); } catch (Exception ignored) { /* Show the recoverable empty state. */ }
        String error = store.error(id);
        boolean yesterday = data != null && data.start != WidgetData.dayStart(System.currentTimeMillis() / 1000d, zone);
        boolean stale = store.updated(id) < System.currentTimeMillis() - 6 * 60000L || !error.isEmpty() || yesterday;
        String scope = o.mode.equals("members") ? "成员" : "公开";
        String smallTitle = data == null ? "今日时刻表" : (yesterday ? DateTimeFormatter.ofPattern("M/d HH:mm") : DateTimeFormatter.ofPattern("今日 HH:mm")).withZone(zone).format(Instant.ofEpochMilli(store.updated(id)));
        v.setTextViewText(R.id.widget_title, m.narrow ? smallTitle : "专注记录 · " + scope);
        v.setTextViewTextSize(R.id.widget_title, TypedValue.COMPLEX_UNIT_SP, m.narrow ? 11 : 14);
        v.setTextViewText(R.id.widget_date, data == null ? "今天" : data.date(zone) + (yesterday ? " 快照" : ""));
        List<WidgetData.Device> devices = data == null ? Collections.emptyList() : data.filtered(o.user, o.device);
        int pages = Math.max(1, (devices.size() + m.capacity - 1) / m.capacity), page = Math.min(store.page(id), pages - 1);
        v.removeAllViews(R.id.widget_rows);
        v.setViewVisibility(R.id.widget_rows, devices.isEmpty() ? View.GONE : View.VISIBLE);
        v.setViewVisibility(R.id.widget_empty, devices.isEmpty() ? View.VISIBLE : View.GONE);
        String empty = !o.configured ? "点击设置\n选择用户与设备" : !error.isEmpty() ? error : data == null ? "等待同步 · 点击刷新" : "暂无设备\n点击设置检查筛选";
        v.setTextViewText(R.id.widget_empty, empty);
        if (data != null) {
            double total = 0; for (WidgetData.Device d : devices) total += d.seconds();
            v.setTextViewText(R.id.widget_summary, (o.user.isEmpty() ? "全部用户" : o.user) + " · " + devices.size() + "台设备相加 " + WidgetData.duration(total));
            if (m.axis && !devices.isEmpty()) {
                v.setViewVisibility(R.id.widget_axis, View.VISIBLE);
                v.setImageViewBitmap(R.id.widget_axis, axis(width - m.padding * 2, font, colors));
            }
            for (int index = page * m.capacity; index < Math.min(devices.size(), (page + 1) * m.capacity); index++) {
                WidgetData.Device d = devices.get(index); RemoteViews row = new RemoteViews(context.getPackageName(), R.layout.widget_device);
                row.setTextViewText(R.id.widget_device_name, m.narrow ? d.name() : d.owner() + " · " + d.name());
                row.setViewVisibility(R.id.widget_device_owner, m.narrow ? View.VISIBLE : View.GONE);
                row.setTextViewText(R.id.widget_device_owner, d.owner()); row.setTextColor(R.id.widget_device_owner, colors.muted);
                if (m.narrow) {
                    row.setTextViewTextSize(R.id.widget_device_name, TypedValue.COMPLEX_UNIT_SP, 11);
                    row.setTextViewTextSize(R.id.widget_device_duration, TypedValue.COMPLEX_UNIT_SP, 10);
                }
                row.setTextViewText(R.id.widget_device_duration, WidgetData.duration(d.seconds()));
                row.setTextColor(R.id.widget_device_name, colors.ink); row.setTextColor(R.id.widget_device_duration, colors.ink);
                row.setTextViewText(R.id.widget_device_status, WidgetData.state(d, stale)); row.setTextColor(R.id.widget_device_status, colors.muted);
                row.setViewVisibility(R.id.widget_device_status, m.status ? View.VISIBLE : View.GONE);
                row.setImageViewBitmap(R.id.widget_device_bar, strip(d, data, Math.max(48, Math.min(800, (int)(width - 2 * m.padding) * 2)), dark, stale));
                String description = d.owner() + "，" + d.name() + "，" + (yesterday ? data.date(zone) : "今日") + WidgetData.duration(d.seconds())
                    + "，" + WidgetData.state(d, stale) + "。时间条从零点到24点，颜色对应应用。点击查看详情";
                row.setContentDescription(R.id.widget_device_row, description);
                row.setOnClickPendingIntent(R.id.widget_device_row, detail(context, id, d));
                v.addView(R.id.widget_rows, row);
            }
        }
        String updated = store.updated(id) == 0 ? "刷新" : DateTimeFormatter.ofPattern("HH:mm").withZone(zone).format(Instant.ofEpochMilli(store.updated(id)));
        String refresh = !error.isEmpty() ? "重试" : m.narrow && pages > 1 ? "↻" : (stale && data != null ? "旧 " : "↻ ") + updated;
        v.setTextViewText(R.id.widget_refresh, refresh);
        v.setContentDescription(R.id.widget_refresh, "点击刷新。" + (store.updated(id) == 0 ? "尚未同步" : "上次更新 " + DateTimeFormatter.ofPattern("M月d日 HH:mm").withZone(zone).format(Instant.ofEpochMilli(store.updated(id)))) + "。" + error);
        v.setTextColor(R.id.widget_refresh, error.isEmpty() ? colors.muted : colors.red);
        for (int view : new int[]{R.id.widget_previous, R.id.widget_page, R.id.widget_next}) v.setViewVisibility(view, pages > 1 ? View.VISIBLE : View.GONE);
        v.setTextViewText(R.id.widget_page, (page + 1) + "/" + pages);
        v.setOnClickPendingIntent(R.id.widget_previous, action(context, id, UsageWidgetProvider.PAGE, (page + pages - 1) % pages));
        v.setOnClickPendingIntent(R.id.widget_next, action(context, id, UsageWidgetProvider.PAGE, (page + 1) % pages));
        return v;
    }
    private static Bitmap axis(float width, float font, Colors colors) {
        int pixels = Math.max(48, Math.min(1200, (int)(width * 2)));
        Bitmap result = Bitmap.createBitmap(pixels, 32, Bitmap.Config.ARGB_8888); Canvas canvas = new Canvas(result);
        Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG); paint.setColor(colors.muted); paint.setTypeface(android.graphics.Typeface.create("sans-serif-condensed", android.graphics.Typeface.NORMAL));
        paint.setTextSize(20 * Math.min(1.3f, font)); Paint.FontMetrics metrics = paint.getFontMetrics(); float baseline = (32 - metrics.ascent - metrics.descent) / 2;
        for (int hour : new int[]{0, 6, 12, 18, 24}) {
            String label = String.format(java.util.Locale.ROOT, "%02d", hour); float text = paint.measureText(label);
            float position = Math.max(0, Math.min(pixels - text, (pixels - 1) * hour / 24f - text / 2));
            canvas.drawText(label, position, baseline, paint);
        }
        return result;
    }
    static Bitmap strip(WidgetData.Device d, WidgetData data, int width, boolean dark, boolean stale) {
        Bitmap bitmap = Bitmap.createBitmap(width, 24, Bitmap.Config.ARGB_8888); Canvas canvas = new Canvas(bitmap);
        Colors colors = new Colors(dark); Paint p = new Paint(Paint.ANTI_ALIAS_FLAG); p.setColor(colors.rule); p.setStrokeWidth(1);
        for (int hour = 0; hour <= 24; hour += 6) { float x = (width - 1) * hour / 24f; canvas.drawLine(x, 0, x, 24, p); }
        canvas.drawLine(0, 12, width, 12, p);
        for (WidgetData.Run run : d.runs()) {
            int index = Palette.IDS.indexOf(run.color()); if (index < 0) index = 0;
            p.setColor(color((dark ? Palette.DARK : Palette.LIGHT)[index]));
            float x = (float)((run.start() - data.start) / (data.end - data.start) * (width - 1));
            float right = (float)((run.end() - data.start) / (data.end - data.start) * (width - 1));
            canvas.drawRect(x, 5, Math.max(x + 1, right), 19, p);
        }
        if (!stale) { p.setColor(colors.red); p.setStrokeWidth(2); float x = (float)((data.now - data.start) / (data.end - data.start) * (width - 1)); canvas.drawLine(x, 0, x, 24, p); }
        return bitmap;
    }
    private static int color(String hex) { return Color.parseColor(hex); }
    private static int dp(Context c, float value) { return Math.round(value * c.getResources().getDisplayMetrics().density); }
    static PendingIntent settings(Context c, int id) {
        Intent i = new Intent(c, WidgetConfigActivity.class).putExtra(AppWidgetManager.EXTRA_APPWIDGET_ID, id)
            .setData(Uri.parse("focusledger-widget://settings/" + id));
        return PendingIntent.getActivity(c, id, i, PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
    }
    private static PendingIntent action(Context c, int id, String action, int page) {
        Intent i = new Intent(c, UsageWidgetProvider.class).setAction(action).putExtra(AppWidgetManager.EXTRA_APPWIDGET_ID, id)
            .putExtra("page", page).setData(Uri.parse("focusledger-widget://action/" + id + "/" + action + "/" + page));
        return PendingIntent.getBroadcast(c, id, i, PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
    }
    private static PendingIntent detail(Context c, int id, WidgetData.Device d) {
        Intent i = new Intent(c, WidgetDetailActivity.class).putExtra(AppWidgetManager.EXTRA_APPWIDGET_ID, id).putExtra("user", d.owner()).putExtra("device", d.id())
            .setData(Uri.parse("focusledger-widget://detail/" + id + "/" + Uri.encode(d.id())));
        return PendingIntent.getActivity(c, id, i, PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
    }
}
