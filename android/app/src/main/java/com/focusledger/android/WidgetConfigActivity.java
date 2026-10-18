package com.focusledger.android;

import android.app.Activity;
import android.appwidget.AppWidgetManager;
import android.content.ComponentName;
import android.content.Intent;
import android.os.Bundle;
import android.text.InputType;
import android.view.View;
import android.widget.AdapterView;
import android.widget.ArrayAdapter;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.Spinner;
import android.widget.TextView;
import android.widget.Toast;
import org.json.JSONObject;
import java.time.Instant;
import java.time.ZoneId;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/** Native configuration, also used as an in-app entry point to add and edit cards. */
public final class WidgetConfigActivity extends Activity {
    private final ExecutorService worker = Executors.newSingleThreadExecutor();
    private int widgetId;
    private Ui ui;
    private WidgetStore store;
    private WidgetStore.Options original, loaded;
    private JSONObject snapshot;
    private long fetchedAt;
    private String loadedIdentity = "";
    private EditText primary, fallback, username, password;
    private Spinner mode, user, device, theme;
    private LinearLayout login, filters;
    private TextView status;
    private Button load, save;
    private final List<String> users = new ArrayList<>(), deviceIds = new ArrayList<>();
    private boolean saved;

    @Override public void onCreate(Bundle state) {
        boolean dark = Ui.dark(this, Agent.get(this).settings.get().theme);
        setTheme(dark ? R.style.AppTheme_Dark : R.style.AppTheme); super.onCreate(state); ui = new Ui(this, dark);
        setResult(RESULT_CANCELED); store = new WidgetStore(this);
        widgetId = getIntent().getIntExtra(AppWidgetManager.EXTRA_APPWIDGET_ID, AppWidgetManager.INVALID_APPWIDGET_ID);
        if (widgetId != AppWidgetManager.INVALID_APPWIDGET_ID && !UsageWidgetProvider.owns(this, widgetId)) { finish(); return; }
        LinearLayout body = body();
        if (widgetId == AppWidgetManager.INVALID_APPWIDGET_ID) { manager(body); return; }
        original = store.options(widgetId); loaded = original;
        Config app = Agent.get(this).settings.get();
        ui.pageTitle(body, "今日时刻表", "原生桌面小组件 · 每张卡片独立设置");
        LinearLayout source = ui.card(body); ui.title(source, "数据来源");
        primary = ui.field(source, "主地址", original.primary.isEmpty() ? app.primary : original.primary, InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
        fallback = ui.field(source, "备用地址（同一个服务端，可留空）", original.configured ? original.fallback : app.fallback, InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
        mode = spinner(source, "查看范围", List.of("公开用户 · 无需登录", "成员用户 · 独立只读授权")); mode.setSelection(original.mode.equals("members") ? 1 : 0);
        login = ui.column(); source.addView(login);
        username = ui.field(login, "用户名", original.account.isEmpty() ? app.username : original.account);
        password = ui.field(login, "密码（仅本次授权使用）", "", InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD); password.setSaveEnabled(false);
        ui.note(login, original.token.isEmpty() ? "登录后生成 180 天只读授权，由系统密钥库加密保存。密码不保存；不会更改上传密钥。需先升级服务端 r13。"
            : "已授权 " + original.account + "，有效至 " + date(original.expires) + "。密码留空继续使用；填写密码可重新授权。");
        mode.setOnItemSelectedListener(selection(() -> login.setVisibility(mode.getSelectedItemPosition() == 1 ? View.VISIBLE : View.GONE)));
        login.setVisibility(original.mode.equals("members") ? View.VISIBLE : View.GONE);
        load = ui.primary("连接并读取设备 / 授权", v -> load()); source.addView(load);
        status = ui.muted("先读取设备，再选择用户与设备。"); status.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE); source.addView(status);
        filters = ui.card(body); ui.title(filters, "显示内容");
        user = spinner(filters, "用户", List.of("全部用户")); device = spinner(filters, "设备", List.of("全部设备"));
        user.setOnItemSelectedListener(selection(this::devices));
        theme = spinner(filters, "外观", List.of("跟随系统", "米白", "炭灰")); theme.setSelection(original.theme.equals("dark") ? 2 : original.theme.equals("light") ? 1 : 0);
        ui.note(filters, "每条横线表示当天 00–24 点，颜色对应网页中的应用。红线表示数据同步时刻；旧快照会隐藏红线。多设备时长相加，超出卡片高度可用 ‹ › 翻页。");
        save = ui.primary("保存小组件", v -> save()); body.addView(save);
        if (!original.token.isEmpty()) body.addView(ui.button("撤销这张小组件的成员授权", v -> revoke()));
        ui.note(body, "长按桌面卡片可调整大小。点击标题或「设置」更改筛选，点击设备查看明细。约每 15 分钟请求后台更新，实际时间由系统调度；可手动刷新。断网显示上次快照及更新时间。");
        snapshot = store.data(widgetId); fetchedAt = store.updated(widgetId);
        if (snapshot != null) { loadedIdentity = original.identity(); populate(); status.setText("已载入上次快照，可调整筛选或重新读取。"); }
    }
    private LinearLayout body() {
        LinearLayout root = ui.column(); root.setBackgroundColor(ui.bg); ui.insets(root);
        ScrollView scroll = new ScrollView(this); LinearLayout body = ui.column(); body.setPadding(ui.dp(18), ui.dp(18), ui.dp(18), ui.dp(18));
        scroll.addView(body); root.addView(scroll); setContentView(root); body.addView(ui.quiet("返回", v -> finish())); return body;
    }
    private void manager(LinearLayout body) {
        ui.pageTitle(body, "桌面小组件", "今日使用时间 · 用户与设备时刻表");
        LinearLayout intro = ui.card(body); ui.title(intro, "添加今日时刻表");
        ui.note(intro, "支持 2×2 小卡片、4×2 横卡片、4×4 大卡片以及拖动缩放。澎湃系统可在桌面双指捏合 → 添加小部件 → 安卓小部件中找到「专注记录 · 今日时刻表」，具体入口名称以当前桌面为准。");
        intro.addView(ui.primary("添加原生小组件", v -> {
            AppWidgetManager manager = AppWidgetManager.getInstance(this);
            try {
                if (!manager.isRequestPinAppWidgetSupported() || !manager.requestPinAppWidget(new ComponentName(this, UsageWidgetProvider.class), null, null))
                    Toast.makeText(this, "请从桌面「安卓小部件」手动添加。", Toast.LENGTH_LONG).show();
                else Toast.makeText(this, "在系统窗口确认添加，再点击桌面卡片设置数据来源。", Toast.LENGTH_LONG).show();
            } catch (RuntimeException e) { Toast.makeText(this, "请从桌面「安卓小部件」手动添加。", Toast.LENGTH_LONG).show(); }
        }));
        LinearLayout cards = ui.card(body); ui.title(cards, "已添加的卡片");
        int[] ids = UsageWidgetProvider.ids(this);
        if (ids.length == 0) ui.note(cards, "还没有添加桌面卡片。");
        for (int id : ids) {
            WidgetStore.Options o = store.options(id);
            cards.addView(ui.button((o.user.isEmpty() ? "全部用户" : o.user) + " · " + (o.mode.equals("members") ? "成员" : "公开") + " · #" + id,
                v -> startActivity(new Intent(this, WidgetConfigActivity.class).putExtra(AppWidgetManager.EXTRA_APPWIDGET_ID, id))));
        }
    }
    private WidgetStore.Options read() {
        WidgetStore.Options o = new WidgetStore.Options(); o.primary = Config.normalizeUrl(primary.getText().toString());
        o.fallback = fallback.getText().toString().trim().isEmpty() ? "" : Config.normalizeUrl(fallback.getText().toString());
        o.mode = mode.getSelectedItemPosition() == 1 ? "members" : "public";
        if (o.mode.equals("members") && loaded.primary.equals(o.primary) && loaded.fallback.equals(o.fallback)) {
            o.token = loaded.token; o.account = loaded.account; o.expires = loaded.expires;
        }
        o.theme = switch (theme.getSelectedItemPosition()) { case 1 -> "light"; case 2 -> "dark"; default -> "system"; };
        return o;
    }
    private void busy(boolean busy, String text) {
        load.setEnabled(!busy); save.setEnabled(!busy); primary.setEnabled(!busy); fallback.setEnabled(!busy); mode.setEnabled(!busy);
        status.setText(text);
    }
    private void load() {
        WidgetStore.Options candidate;
        try { candidate = read(); } catch (Exception e) { status.setText(e.getMessage()); return; }
        String name = username.getText().toString(), secret = password.getText().toString(); password.setText("");
        busy(true, "正在连接…");
        worker.execute(() -> {
            WidgetNetwork network = new WidgetNetwork();
            try {
                if (candidate.mode.equals("members") && (candidate.token.isEmpty() || !secret.isEmpty())) network.authorize(candidate, name, secret);
                JSONObject data = network.fetch(candidate); WidgetData.parse(data, ZoneId.systemDefault());
                runOnUiThread(() -> {
                    if (isFinishing() || isDestroyed()) { if (!candidate.token.equals(original.token)) WidgetRefreshJob.revokeLater(this, candidate); return; }
                    if (!loaded.token.equals(original.token) && !loaded.token.equals(candidate.token)) WidgetRefreshJob.revokeLater(this, loaded);
                    loaded = candidate; snapshot = data; fetchedAt = System.currentTimeMillis(); loadedIdentity = candidate.identity();
                    populate(); busy(false, candidate.mode.equals("members") ? "已读取成员设备 · " + candidate.account : "已读取公开设备");
                });
            } catch (Exception e) {
                if (!candidate.token.equals(original.token) && !candidate.token.equals(loaded.token)) WidgetRefreshJob.revokeLater(this, candidate);
                runOnUiThread(() -> { if (!isFinishing()) busy(false, WidgetNetwork.message(e)); });
            }
        });
    }
    private void populate() {
        try {
            WidgetData data = WidgetData.parse(snapshot, ZoneId.systemDefault()); users.clear(); users.add("");
            for (WidgetData.Device d : data.devices) if (!users.contains(d.owner())) users.add(d.owner());
            List<String> labels = new ArrayList<>(); labels.add("全部用户"); labels.addAll(users.subList(1, users.size()));
            user.setAdapter(adapter(labels)); user.setSelection(Math.max(0, users.indexOf(original.user))); devices();
        } catch (Exception e) { status.setText("看板数据无效，请重新读取"); }
    }
    private void devices() {
        if (snapshot == null || users.isEmpty()) return;
        try {
            String selected = users.get(Math.max(0, user.getSelectedItemPosition())); List<String> labels = new ArrayList<>();
            labels.add("全部设备"); deviceIds.clear(); deviceIds.add("");
            for (WidgetData.Device d : WidgetData.parse(snapshot, ZoneId.systemDefault()).filtered(selected, "")) { labels.add(d.owner() + " · " + d.name()); deviceIds.add(d.id()); }
            device.setAdapter(adapter(labels)); device.setSelection(Math.max(0, deviceIds.indexOf(original.device)));
        } catch (Exception e) { status.setText("设备列表无效，请重新读取"); }
    }
    private void save() {
        try {
            WidgetStore.Options candidate = read();
            if (snapshot == null || !candidate.identity().equals(loadedIdentity)) { status.setText("来源或查看范围已变化，请先连接并读取设备。"); return; }
            if (!UsageWidgetProvider.owns(this, widgetId)) { finish(); return; }
            candidate.user = users.get(Math.max(0, user.getSelectedItemPosition())); candidate.device = deviceIds.get(Math.max(0, device.getSelectedItemPosition()));
            store.save(widgetId, candidate); store.success(widgetId, candidate.identity(), snapshot, fetchedAt);
            if (!original.token.isEmpty() && !original.token.equals(candidate.token)) WidgetRefreshJob.revokeLater(this, original);
            saved = true; UsageWidgetProvider.render(this, widgetId); WidgetRefreshJob.schedule(this); WidgetRefreshJob.request(this);
            setResult(RESULT_OK, new Intent().putExtra(AppWidgetManager.EXTRA_APPWIDGET_ID, widgetId)); finish();
        } catch (Exception e) { status.setText(e.getMessage()); }
    }
    private void revoke() {
        busy(true, "正在撤销授权…");
        worker.execute(() -> {
            try {
                new WidgetNetwork().revoke(original);
                original.token = ""; original.account = ""; original.expires = 0; store.save(widgetId, original);
                store.failure(widgetId, original.identity(), "授权已撤销 · 点击设置重新授权", true);
                runOnUiThread(() -> { UsageWidgetProvider.render(this, widgetId); saved = true; finish(); });
            } catch (Exception e) { runOnUiThread(() -> busy(false, WidgetNetwork.message(e))); }
        });
    }
    private Spinner spinner(LinearLayout parent, String label, List<String> entries) {
        TextView text = ui.muted(label); text.setPadding(0, ui.dp(10), 0, ui.dp(4)); parent.addView(text);
        Spinner spinner = new Spinner(this); spinner.setId(View.generateViewId()); text.setLabelFor(spinner.getId());
        spinner.setAdapter(adapter(entries)); spinner.setBackgroundTintList(ui.controlColors()); parent.addView(spinner, new LinearLayout.LayoutParams(-1, ui.dp(48))); return spinner;
    }
    private ArrayAdapter<String> adapter(List<String> entries) {
        ArrayAdapter<String> adapter = new ArrayAdapter<>(this, android.R.layout.simple_spinner_item, entries);
        adapter.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item); return adapter;
    }
    private static AdapterView.OnItemSelectedListener selection(Runnable action) {
        return new AdapterView.OnItemSelectedListener() {
            @Override public void onItemSelected(AdapterView<?> parent, View view, int position, long id) { action.run(); }
            @Override public void onNothingSelected(AdapterView<?> parent) {}
        };
    }
    private static String date(double seconds) { return DateTimeFormatter.ofPattern("yyyy-MM-dd").withZone(ZoneId.systemDefault()).format(Instant.ofEpochSecond((long)seconds)); }
    @Override protected void onDestroy() {
        if (!saved && original != null && loaded != null && !loaded.token.isEmpty() && !loaded.token.equals(original.token)) WidgetRefreshJob.revokeLater(this, loaded);
        worker.shutdown(); super.onDestroy();
    }
}
