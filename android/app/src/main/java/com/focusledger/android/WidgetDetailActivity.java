package com.focusledger.android;

import android.app.Activity;
import android.appwidget.AppWidgetManager;
import android.content.Intent;
import android.graphics.Color;
import android.net.Uri;
import android.os.Bundle;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import java.time.Instant;
import java.time.ZoneId;
import java.time.format.DateTimeFormatter;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/** A row opens its actual device and coloured app intervals without needing a second web login. */
public final class WidgetDetailActivity extends Activity {
    private final ExecutorService worker = Executors.newSingleThreadExecutor();
    private int id;
    private Ui ui;
    private LinearLayout body;
    @Override public void onCreate(Bundle state) {
        id = getIntent().getIntExtra(AppWidgetManager.EXTRA_APPWIDGET_ID, AppWidgetManager.INVALID_APPWIDGET_ID);
        boolean dark = WidgetRenderer.dark(this, new WidgetStore(this).options(id).theme);
        setTheme(dark ? R.style.AppTheme_Dark : R.style.AppTheme); super.onCreate(state); ui = new Ui(this, dark);
        if (!UsageWidgetProvider.owns(this, id)) { finish(); return; }
        LinearLayout root = ui.column(); root.setBackgroundColor(new WidgetRenderer.Colors(dark).paper()); ui.insets(root);
        ScrollView scroll = new ScrollView(this); body = ui.column(); body.setPadding(ui.dp(18), ui.dp(18), ui.dp(18), ui.dp(18)); scroll.addView(body); root.addView(scroll); setContentView(root);
    }
    @Override protected void onResume() { super.onResume(); if (body != null) render(); }
    private void render() {
        body.removeAllViews(); body.addView(ui.quiet("返回桌面", v -> finish()));
        WidgetStore store = new WidgetStore(this); WidgetStore.Options o = store.options(id); WidgetData data;
        try { data = WidgetData.parse(store.data(id), ZoneId.systemDefault()); }
        catch (Exception e) {
            ui.pageTitle(body, "设备记录", store.error(id).isEmpty() ? "暂无可用快照" : store.error(id));
            body.addView(ui.primary("设置小组件", v -> startActivity(new Intent(this, WidgetConfigActivity.class).putExtra(AppWidgetManager.EXTRA_APPWIDGET_ID, id)))); return;
        }
        String user = getIntent().getStringExtra("user"), device = getIntent().getStringExtra("device");
        java.util.List<WidgetData.Device> devices = data.filtered(user == null ? "" : user, device == null ? "" : device);
        if (devices.isEmpty()) { ui.pageTitle(body, "设备记录", "设备已不可见，或已从服务端移除。"); return; }
        WidgetData.Device d = devices.get(0);
        boolean stale = store.updated(id) < System.currentTimeMillis() - 6 * 60000 || !store.error(id).isEmpty();
        ui.pageTitle(body, d.name(), d.owner() + " · " + data.date(ZoneId.systemDefault()) + " · " + WidgetData.state(d, stale));
        LinearLayout overview = ui.card(body); ui.title(overview, "当天累计 " + WidgetData.duration(d.seconds()));
        ui.note(overview, "00:00                                      12:00                                    24:00");
        ImageView chart = new ImageView(this); chart.setImageBitmap(WidgetRenderer.strip(d, data, 720, ui.dark, stale));
        chart.setScaleType(ImageView.ScaleType.FIT_XY); chart.setContentDescription("当天应用时间条，颜色与网页相同"); overview.addView(chart, new LinearLayout.LayoutParams(-1, ui.dp(32)));
        ui.note(overview, "快照更新于 " + DateTimeFormatter.ofPattern("M月d日 HH:mm").withZone(ZoneId.systemDefault()).format(Instant.ofEpochMilli(store.updated(id)))
            + (store.error(id).isEmpty() ? "" : "\n" + store.error(id)));
        overview.addView(ui.button("立即刷新", v -> {
            v.setEnabled(false);
            worker.execute(() -> {
                try { org.json.JSONObject fresh = new WidgetNetwork().fetch(o); WidgetData.parse(fresh, ZoneId.systemDefault()); store.success(id, o.identity(), fresh); }
                catch (Exception e) { store.failure(id, o.identity(), WidgetNetwork.message(e), e instanceof Transport.ApiError api && (api.status == 401 || api.status == 403)); }
                runOnUiThread(() -> { if (!isFinishing() && !isDestroyed()) { UsageWidgetProvider.render(this, id); render(); } });
            });
        }));
        LinearLayout apps = ui.card(body); ui.title(apps, "应用时长"); Map<String, Double> totals = new LinkedHashMap<>(); Map<String, String> colors = new LinkedHashMap<>();
        for (WidgetData.Run run : d.runs()) { totals.merge(run.app(), run.end() - run.start(), Double::sum); colors.put(run.app(), run.color()); }
        if (totals.isEmpty()) ui.note(apps, "这一天没有使用记录。");
        totals.entrySet().stream().sorted(Map.Entry.<String, Double>comparingByValue().reversed()).limit(30).forEach(entry -> {
            TextView row = ui.text("●  " + entry.getKey() + "    " + WidgetData.duration(entry.getValue()), 14, false);
            int index = Palette.IDS.indexOf(colors.get(entry.getKey())); if (index < 0) index = 0;
            row.setTextColor(Color.parseColor((ui.dark ? Palette.DARK : Palette.LIGHT)[index])); row.setPadding(0, ui.dp(8), 0, ui.dp(8)); apps.addView(row);
        });
        LinearLayout intervals = ui.card(body); ui.title(intervals, "最近使用时段");
        DateTimeFormatter hm = DateTimeFormatter.ofPattern("HH:mm").withZone(ZoneId.systemDefault());
        for (int index = d.runs().size() - 1; index >= Math.max(0, d.runs().size() - 30); index--) {
            WidgetData.Run run = d.runs().get(index);
            ui.note(intervals, hm.format(Instant.ofEpochSecond((long)run.start())) + "–" + hm.format(Instant.ofEpochSecond((long)run.end())) + "  " + run.app() + " · " + WidgetData.duration(run.end() - run.start()));
        }
        if (d.runs().isEmpty()) ui.note(intervals, "暂无记录。");
        body.addView(ui.button("打开网页历史记录", v -> startActivity(new Intent(this, BoardActivity.class).putExtra("base", o.primary)
            .putExtra("path", "/people/" + Uri.encode(d.owner()) + "?device=" + Uri.encode(d.id()) + "&span=day"))));
        ui.note(body, "这里显示与桌面相同的设备快照。网页中的非公开历史记录仍需按网页规则登录。");
    }
    @Override protected void onDestroy() { worker.shutdown(); super.onDestroy(); }
}
