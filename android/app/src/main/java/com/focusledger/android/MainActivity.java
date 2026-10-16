package com.focusledger.android;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.text.SpannableString;
import android.text.Spanned;
import android.text.style.ForegroundColorSpan;
import android.text.style.RelativeSizeSpan;
import android.view.View;
import android.widget.FrameLayout;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;
import org.json.JSONArray;
import org.json.JSONObject;
import java.time.LocalDate;
import java.time.ZoneId;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

public final class MainActivity extends Activity {
    interface Work<T> { T run() throws Exception; }
    Agent agent; Ui ui; LinearLayout body; ScrollView scroll;
    FrameLayout pages; BottomNavigation nav;
    int selected;
    private final Handler main = new Handler(Looper.getMainLooper());
    private final Map<String,TextView> live = new HashMap<>();
    private Button trackingControl;
    private boolean saving;
    private final Runnable refresh = new Runnable() { @Override public void run() { refreshLive(); main.postDelayed(this, 2000); } };
    @Override public void onCreate(Bundle state) {
        agent = Agent.get(this); Config c = agent.settings.get(); boolean dark = Ui.dark(this, c.theme);
        setTheme(dark ? R.style.AppTheme_Dark : R.style.AppTheme);
        super.onCreate(state); ui = new Ui(this, dark);
        if (state != null) selected = Math.max(0, Math.min(4, state.getInt("tab", 0)));
        LinearLayout root = ui.column(); root.setBackgroundColor(ui.bg); ui.insets(root);
        LinearLayout header = ui.row(); header.setPadding(ui.dp(22), ui.dp(12), ui.dp(20), ui.dp(12));
        LinearLayout brand = ui.column(); TextView wordmark = ui.text("FOCUS LEDGER", 10, true); wordmark.setTextColor(ui.muted); wordmark.setLetterSpacing(.18f);
        brand.addView(wordmark); TextView name = ui.text("专注记录", 24, true); name.setPadding(0, ui.dp(4), 0, 0); brand.addView(name);
        header.addView(brand, new LinearLayout.LayoutParams(0, -2, 1)); header.addView(ui.iconButton(Icons.THEME, "外观主题", v -> chooseTheme())); root.addView(header);
        pages = new FrameLayout(this); root.addView(pages, new LinearLayout.LayoutParams(-1, 0, 1));
        LinearLayout dock = ui.column(); dock.setPadding(ui.dp(16), ui.dp(8), ui.dp(16), ui.dp(10));
        nav = new BottomNavigation(ui, this::show);
        int navHeight = ui.dp(76 + Math.max(0, getResources().getConfiguration().fontScale - 1) * 20);
        dock.addView(nav, new LinearLayout.LayoutParams(-1, navHeight)); root.addView(dock);
        setContentView(root); renderPage(0, false);
        if (agent.settings.wanted() && c.configured() && agent.service == null) KeepAlive.start(this, CollectorService.ACTION_RECOVER);
    }
    @Override protected void onResume() { super.onResume(); main.removeCallbacks(refresh); main.post(refresh); }
    @Override protected void onPause() { main.removeCallbacks(refresh); if (pages != null) PageMotion.settle(pages); if (nav != null) nav.settle(); super.onPause(); }
    @Override protected void onDestroy() { main.removeCallbacksAndMessages(null); super.onDestroy(); }
    @Override protected void onSaveInstanceState(Bundle state) { state.putInt("tab", selected); super.onSaveInstanceState(state); }
    void show(int tab) {
        if (tab < 0 || tab > 4) return;
        if (selected == tab) { scroll.smoothScrollTo(0, 0); return; }
        int direction = Integer.compare(tab, selected); selected = tab;
        View focus = getCurrentFocus(); if (focus != null) {
            getSystemService(android.view.inputmethod.InputMethodManager.class).hideSoftInputFromWindow(focus.getWindowToken(), 0); focus.clearFocus();
        }
        renderPage(direction, true);
    }
    void render() { renderPage(0, true); }
    private void renderPage(int direction, boolean animate) {
        ScrollView previous = scroll; int offset = direction == 0 && previous != null ? previous.getScrollY() : 0;
        live.clear(); trackingControl = null;
        scroll = new ScrollView(this); scroll.setFillViewport(true); scroll.setClipToPadding(false); scroll.setVerticalScrollBarEnabled(false);
        scroll.setBackgroundColor(ui.bg); body = ui.column(); body.setFocusableInTouchMode(true);
        body.setPadding(ui.dp(18), ui.dp(12), ui.dp(18), ui.dp(12)); scroll.addView(body);
        String[] titles = {"今日概览", "使用记录", "连接设置", "后台守护", "服务端"};
        String[] subtitles = {LocalDate.now().format(java.time.format.DateTimeFormatter.ofPattern("M月d日 · EEEE", java.util.Locale.SIMPLIFIED_CHINESE)),
            "这台设备留下的时间片段", "让记录在设备之间同步", "安心记录，从完整授权开始", "账户管理与完整看板"};
        ui.pageTitle(body, titles[selected], subtitles[selected]); nav.select(selected, animate && direction != 0);
        switch (selected) {
            case 0 -> overview(); case 1 -> history(); case 2 -> new ConnectionPane(this).build();
            case 3 -> new KeepAlivePane(this).build(); case 4 -> new ServerPane(this).build();
        }
        refreshLive(); PageMotion.show(pages, previous, scroll, direction, ui, animate);
        if (offset > 0) { ScrollView current = scroll; current.post(() -> { if (scroll == current) current.scrollTo(0, offset); }); }
    }
    TextView dynamic(LinearLayout box, String key, int size, boolean bold) { TextView t = ui.text("", size, bold); live.put(key, t); box.addView(t); return t; }
    private void overview() {
        Config c = agent.settings.get();
        LinearLayout hero = ui.card(body);
        TextView state = dynamic(hero, "state", 12, true); state.setTextColor(ui.accent); state.setBackground(ui.shape(ui.accentSoft, 0, 10));
        state.setPadding(ui.dp(10), ui.dp(7), ui.dp(10), ui.dp(7)); state.setLayoutParams(new LinearLayout.LayoutParams(-2, -2));
        TextView totalLabel = ui.muted("今日累计使用"); totalLabel.setPadding(0, ui.dp(22), 0, ui.dp(8)); hero.addView(totalLabel);
        TextView total = dynamic(hero, "today", 40, true); total.setMaxLines(1); total.setFontFeatureSettings("tnum");
        total.setAutoSizeTextTypeUniformWithConfiguration(24, 40, 1, android.util.TypedValue.COMPLEX_UNIT_SP);
        TextView device = ui.muted(c.deviceName + (c.username.isEmpty() ? "" : "  ·  " + c.username)); device.setTextSize(12);
        device.setMaxLines(1); device.setEllipsize(android.text.TextUtils.TruncateAt.END); device.setPadding(0, ui.dp(10), 0, ui.dp(18)); hero.addView(device);
        TextView current = dynamic(hero, "current", 14, true); current.setBackground(ui.shape(ui.surface, 0, 14));
        current.setPadding(ui.dp(12), ui.dp(12), ui.dp(12), ui.dp(12));
        TextView pending = dynamic(hero, "pending", 12, false); pending.setTextColor(ui.muted); pending.setPadding(ui.dp(2), ui.dp(10), 0, 0);
        trackingControl = ui.primary("开始采集", v -> control());
        Button upload = ui.button("立即上传", v -> upload()); ui.icon(upload, Icons.UPLOAD); ui.actions(hero, trackingControl, upload);
        if (agent.settings.wanted()) hero.addView(ui.quiet("停止后台服务", v -> confirm("停止后台服务", "停止后不再自动采集或恢复。已有记录会保留，可随时手动开始。", () -> { agent.stop(); main.postDelayed(this::render, 500); })));
        LinearLayout sync = ui.card(body); ui.title(sync, "同步状态"); dynamic(sync, "upload", 14, true);
        TextView endpoint = dynamic(sync, "endpoint", 12, false); endpoint.setTextColor(ui.muted); endpoint.setPadding(0, ui.dp(7), 0, ui.dp(2));
        dynamic(sync, "error", 12, false).setTextColor(ui.accent);
        Button board = ui.button("打开服务端看板", v -> openBoard(null)); ui.trailingIcon(board, Icons.ARROW); sync.addView(board);
        LinearLayout ranks = ui.card(body); ui.title(ranks, "今天用在了哪里"); rankRows(ranks, todayStart(), System.currentTimeMillis(), 6);
        LinearLayout privacy = ui.card(body); privacy.setBackground(ui.shape(ui.surface, 0, 22)); ui.title(privacy, "只记录使用情况");
        ui.note(privacy, "仅记录前台应用名称、包名、起止时间和设备电量。不读取聊天内容、窗口文字、截图、键盘输入或文件内容。锁屏和熄屏停止计时。");
        if (!agent.settings.warning.isEmpty()) ui.note(privacy, agent.settings.warning);
    }
    private void history() {
        LinearLayout intro = ui.card(body); ui.title(intro, "本机记录");
        ui.note(intro, "显示最近 100 条缓存记录。已上传记录本机保留 7 天，待上传最多 30 天；完整日 / 周 / 月 / 年统计在服务端看板查看。");
        ui.actions(intro, ui.button("刷新记录", v -> render()), ui.button("完整统计", v -> openBoard(null)));
        List<LedgerStore.Row> rows = agent.store.recent(agent.settings.get().scope, 100); Config c = agent.settings.get();
        if (rows.isEmpty()) ui.note(intro, "开始采集后，记录会出现在这里。");
        LinearLayout records = rows.isEmpty() ? null : ui.card(body);
        int recordIndex = 0;
        for (LedgerStore.Row row : rows) {
            if (recordIndex++ > 0) ui.divider(records);
            JSONObject event = row.event(); LinearLayout box = ui.column(); records.addView(box);
            boolean usage = "app_usage".equals(event.optString("kind")); String pkg = event.optString("process_name");
            TextView title = ui.text(usage ? c.displayName(pkg, event.optString("app_name")) : statusName(event.optString("reason")), 16, true);
            if (usage) title.setTextColor(Palette.color(c, pkg, ui.dark)); title.setMaxLines(1); title.setEllipsize(android.text.TextUtils.TruncateAt.END);
            LinearLayout heading = ui.row(); heading.addView(title, new LinearLayout.LayoutParams(0, -2, 1));
            TextView badge = ui.badge(row.sent() == 1 ? "已同步" : row.sent() == 2 ? "需检查" : "待上传");
            if (row.sent() == 1) { badge.setTextColor(ui.muted); badge.setBackground(ui.shape(ui.surface, 0, 10)); }
            LinearLayout.LayoutParams badgeSize = new LinearLayout.LayoutParams(-2, -2); badgeSize.setMarginStart(ui.dp(8)); heading.addView(badge, badgeSize); box.addView(heading);
            String timestamp = event.optString(usage ? "started_at" : "occurred_at");
            String line = timestamp;
            try { line = Ui.clock(java.time.Instant.parse(timestamp).toEpochMilli()); } catch (Exception ignored) {}
            if (usage) line += "  ·  " + Ui.duration(event.optDouble("duration_seconds"));
            else if (!event.isNull("battery_percent")) line += "  ·  电量 " + event.optInt("battery_percent") + "%" + (event.optBoolean("charging") ? " · 充电中" : "");
            ui.note(box, line);
            if (usage) { TextView packageName = ui.muted(pkg); packageName.setTextSize(11); packageName.setMaxLines(1); packageName.setEllipsize(android.text.TextUtils.TruncateAt.END); box.addView(packageName);
                box.setBackground(ui.ripple(0, 0, 10)); box.setOnClickListener(v -> new AppRulesPane(this).edit(pkg, event.optString("app_name"))); }
        }
    }
    void rankRows(LinearLayout parent, long from, long to, int max) {
        Config c = agent.settings.get(); List<LedgerStore.Rank> ranks = agent.store.ranking(c.scope, from, to);
        if (ranks.isEmpty()) { TextView empty = ui.text("还没有使用记录", 15, true); empty.setPadding(0, ui.dp(12), 0, ui.dp(6)); parent.addView(empty); ui.note(parent, "开始采集后，时间分布会显示在这里。"); return; }
        double biggest = ranks.get(0).seconds();
        for (int i = 0; i < Math.min(max, ranks.size()); i++) {
            LedgerStore.Rank rank = ranks.get(i); LinearLayout row = ui.column(); row.setPadding(0, ui.dp(10), 0, ui.dp(10));
            LinearLayout labels = ui.row(); TextView name = ui.text(c.displayName(rank.pkg(), rank.label()), 14, true);
            TextView number = ui.text(String.format(java.util.Locale.ROOT, "%02d", i + 1), 11, true); number.setTextColor(Palette.color(c, rank.pkg(), ui.dark));
            labels.addView(number, new LinearLayout.LayoutParams(ui.dp(28), -2));
            name.setMaxLines(1); name.setEllipsize(android.text.TextUtils.TruncateAt.END); labels.addView(name, new LinearLayout.LayoutParams(0, -2, 1));
            TextView duration = ui.muted(Ui.duration(rank.seconds())); duration.setTextSize(12); duration.setPadding(ui.dp(8), 0, 0, 0); labels.addView(duration); row.addView(labels);
            LinearLayout track = ui.row(); track.setBackground(ui.shape(ui.line, 0, 3));
            android.view.View fill = new android.view.View(this); fill.setBackground(ui.shape(Palette.color(c, rank.pkg(), ui.dark), 0, 3));
            track.addView(fill, new LinearLayout.LayoutParams(0, ui.dp(5), (float)Math.max(.01, rank.seconds()/biggest)));
            track.addView(new android.view.View(this), new LinearLayout.LayoutParams(0, ui.dp(5), (float)Math.max(.001, 1-rank.seconds()/biggest)));
            LinearLayout.LayoutParams bar = new LinearLayout.LayoutParams(-1, ui.dp(5)); bar.topMargin = ui.dp(7); row.addView(track, bar); parent.addView(row);
            row.setOnClickListener(v -> new AppRulesPane(this).edit(rank.pkg(), rank.label()));
        }
    }
    private void refreshLive() {
        if (isFinishing() || isDestroyed()) return;
        try {
            Config c = agent.settings.get();
            put("state", !c.configured() ? "先连接你的服务器" : !UsageReader.permitted(this) ? "等待使用情况权限" : agent.service == null ? "后台服务未运行" : agent.settings.tracking() ? "● 正在采集 · " + c.modeName() : "已暂停采集 · " + c.modeName());
            if (live.containsKey("today")) {
                double seconds = 0; for (LedgerStore.Rank rank : agent.store.ranking(c.scope, todayStart(), System.currentTimeMillis())) seconds += rank.seconds();
                String value = Ui.duration(seconds); TextView total = live.get("today");
                if (!total.getText().toString().equals(value)) {
                    SpannableString styled = new SpannableString(value); java.util.regex.Matcher units = java.util.regex.Pattern.compile("小时|分|秒").matcher(value);
                    while (units.find()) { styled.setSpan(new RelativeSizeSpan(.42f), units.start(), units.end(), Spanned.SPAN_EXCLUSIVE_EXCLUSIVE); styled.setSpan(new ForegroundColorSpan(ui.muted), units.start(), units.end(), Spanned.SPAN_EXCLUSIVE_EXCLUSIVE); }
                    total.setText(styled);
                }
            }
            if (trackingControl != null) {
                boolean tracking = agent.service != null && agent.settings.tracking(); trackingControl.setText(tracking ? "暂停采集" : "开始 / 继续"); ui.icon(trackingControl, tracking ? Icons.PAUSE : Icons.PLAY);
            }
            JSONObject app = agent.foreground(c).optJSONObject("app");
            put("current", app == null ? "当前：锁屏、空闲或未采集" : "当前：" + c.displayName(app.optString("process_name"), app.optString("app_name")));
            int pending = agent.store.count(c.scope, false), all = agent.store.count(c.scope, true);
            put("pending", "待上传 " + pending + " 条" + (all > pending ? " · 其他连接 " + (all-pending) + " 条" : ""));
            put("upload", agent.uploader.busy() ? "正在同步记录…" : "最近同步  " + Ui.clock(longValue(agent.store.get(c.scope+":last_upload", "0"))));
            put("endpoint", agent.store.get(c.scope+":last_endpoint", c.primary.isEmpty() ? "连接服务器后自动同步" : c.primary));
            String error = agent.store.get(c.scope+":last_error", ""); if (!agent.captureNote.isEmpty()) error = agent.captureNote + "\n" + error;
            put("error", error);
            put("usage_permission", UsageReader.permitted(this) ? "使用情况访问：已授权" : "使用情况访问：未授权");
            put("battery_permission", KeepAlive.batteryExempt(this) ? "系统电池优化：已豁免" : "系统电池优化：仍在限制");
            put("notifications", KeepAlive.notifications(this) ? "通知：已允许" : "通知：已关闭，建议允许持续记录状态通知");
            put("health", "后台服务：" + (agent.service == null ? "未运行" : "运行中") + "\n最近采集：" + Ui.clock(longValue(agent.store.get("last_capture", "0")))
                + "\n恢复任务：" + (getSystemService(android.app.job.JobScheduler.class).getPendingJob(KeepAlive.PERIODIC_JOB) == null ? "未登记" : "已登记（执行时间由系统决定）")
                + "\n" + agent.store.get("recovery_note", "") + "\n" + agent.store.get(c.scope+":metadata_note", "") + "\n" + agent.store.get(c.scope+":validation_note", ""));
        } catch (Exception e) { put("error", Agent.message(e)); }
    }
    private void put(String key, String text) { TextView t = live.get(key); if (t != null) { String value = text.trim(); if (!t.getText().toString().equals(value)) t.setText(value); if (key.equals("error")) t.setVisibility(value.isEmpty() ? View.GONE : View.VISIBLE); } }
    static long longValue(String text) { try { return Long.parseLong(text); } catch (Exception e) { return 0; } }
    static long todayStart() { return LocalDate.now().atStartOfDay(ZoneId.systemDefault()).toInstant().toEpochMilli(); }
    static String statusName(String reason) { return switch (reason) { case "startup" -> "设备启动 / 采集启动"; case "shutdown" -> "关机"; case "suspend" -> "熄屏"; case "resume" -> "解锁 / 恢复"; default -> "电池与电源状态"; }; }
    void control() {
        if (!agent.settings.get().configured()) { show(2); return; }
        if (!UsageReader.permitted(this)) { new AlertDialog.Builder(this).setTitle("允许读取应用使用情况").setMessage("用于统计本机前台应用与使用时长。授权后返回 App，点击开始采集。")
            .setPositiveButton("去授权", (d,w) -> KeepAlive.usageSettings(this)).setNegativeButton("取消", null).show(); return; }
        if (agent.service != null && !agent.settings.wanted()) { toast("正在停止服务，请稍后再开始"); return; }
        if (agent.service != null) agent.toggleTracking();
        else if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, 41);
        else agent.begin();
        main.postDelayed(this::render, 500);
    }
    @Override public void onRequestPermissionsResult(int code, String[] permissions, int[] results) { super.onRequestPermissionsResult(code, permissions, results); if (code == 41) { agent.begin(); main.postDelayed(this::render, 500); } }
    void upload() {
        if (!agent.settings.get().configured()) { show(2); return; }
        agent.collector.execute(() -> { try { if (agent.settings.tracking()) agent.capture(agent.settings.get(), false); agent.uploader.request(true, true); } catch (Exception e) { toast(Agent.message(e)); } }); toast("正在尝试同步，结果会显示在同步状态中");
    }
    void verifyAndSave(Config candidate, Runnable done) {
        if (saving) { toast("正在验证并保存，请稍候"); return; } saving = true; toast("正在验证并保存设置…");
        Config old = agent.settings.get();
        boolean connectionChanged = !old.configured() || !old.primary.equals(candidate.primary) || !old.fallback.equals(candidate.fallback) || !old.apiKey.equals(candidate.apiKey) || !old.deviceName.equals(candidate.deviceName);
        io(() -> {
            candidate.validate(); Config bound = candidate;
            if (connectionChanged) {
                JSONObject checked = agent.transport.check(candidate); bound = agent.settings.bind(candidate, checked);
                agent.transport.request(bound, "POST", "/api/v1/usage/batches", new JSONObject().put("schema_version", 1).put("device", bound.device()).put("events", new JSONArray()));
            }
            return bound;
        }, bound -> agent.saveConfig(bound, () -> runOnUiThread(() -> { saving = false; agent.settings.prefs.edit().remove("draft_key").remove("draft_primary").remove("draft_fallback").apply(); toast("设置已保存"); done.run(); }), error -> runOnUiThread(() -> { saving = false; toast(error); })), error -> { saving = false; toast(error); });
    }
    <T> void io(Work<T> work, java.util.function.Consumer<T> done) {
        io(work, done, this::toast);
    }
    <T> void io(Work<T> work, java.util.function.Consumer<T> done, java.util.function.Consumer<String> failure) {
        agent.io.execute(() -> { try { T result = work.run(); runOnUiThread(() -> { if (!isDestroyed()) done.accept(result); }); } catch (Exception e) { runOnUiThread(() -> { if (!isDestroyed()) failure.accept(Agent.message(e)); }); } });
    }
    void toast(String value) { runOnUiThread(() -> { if (!isDestroyed()) Toast.makeText(this, value, Toast.LENGTH_LONG).show(); }); }
    void confirm(String title, String message, Runnable action) { new AlertDialog.Builder(this).setTitle(title).setMessage(message).setPositiveButton("确认", (d,w) -> action.run()).setNegativeButton("取消", null).show(); }
    void openBoard(String base) {
        if (base == null) { Config c = agent.settings.get(); if (c.primary.isEmpty()) { toast("请先填写服务器地址"); show(2); return; } base = agent.transport.activeUrl(c); }
        startActivity(new Intent(this, BoardActivity.class).putExtra("base", base));
    }
    private void chooseTheme() {
        String[] labels = {"跟随系统", "浅色", "深色"}; String[] values = {"system", "light", "dark"};
        new AlertDialog.Builder(this).setTitle("外观主题").setSingleChoiceItems(labels, java.util.Arrays.asList(values).indexOf(agent.settings.get().theme), (d,w) -> {
            d.dismiss(); agent.collector.execute(() -> { try { Config c = agent.settings.get(); agent.settings.appearance(c.mode, values[w]); runOnUiThread(this::recreate); } catch (Exception e) { toast(Agent.message(e)); } });
        }).setNegativeButton("取消", null).show();
    }
}
