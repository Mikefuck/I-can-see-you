package com.focusledger.android;

import android.app.AlertDialog;
import android.content.Intent;
import android.content.pm.ResolveInfo;
import android.text.Editable;
import android.text.TextWatcher;
import android.widget.ArrayAdapter;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ListView;
import android.widget.ScrollView;
import android.widget.Spinner;
import org.json.JSONObject;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

final class AppRulesPane {
    final MainActivity a; final Ui ui; final Agent agent;
    AppRulesPane(MainActivity a) { this.a = a; ui = a.ui; agent = a.agent; }
    void show() {
        LinearLayout content = ui.column(); content.setPadding(ui.dp(16), 0, ui.dp(16), ui.dp(12));
        content.addView(ui.button("搜索已安装 / 最近使用的应用", v -> picker()));
        content.addView(ui.button("手动添加包名", v -> edit("", "")));
        Config c = agent.settings.get(); java.util.Set<String> packages = new java.util.TreeSet<>(Config.keys(c.aliases)); packages.addAll(Config.keys(c.colors));
        for (String pkg : packages) content.addView(ui.button(c.aliases.optString(pkg, pkg) + " · " + Palette.NAMES[Math.max(0, Palette.IDS.indexOf(c.colors.optString(pkg, Palette.defaultId(pkg))))], v -> edit(pkg, agent.reader.label(pkg))));
        content.addView(ui.button("恢复全部默认颜色", v -> a.confirm("恢复默认颜色", "清除所有手动配色，保留应用显示名称。联网后同步服务端历史配色。", () -> save(next -> next.colors = new JSONObject()))));
        ScrollView scroll = new ScrollView(a); scroll.addView(content); new AlertDialog.Builder(a).setTitle("应用名称与颜色").setView(scroll).setNegativeButton("关闭", null).show();
    }
    void edit(String pkg, String label) {
        Config c = agent.settings.get(); String key = pkg.toLowerCase(Locale.ROOT);
        LinearLayout box = ui.column(); box.setPadding(ui.dp(20), 0, ui.dp(20), ui.dp(8));
        EditText packageInput = ui.field(box, "应用包名", pkg);
        EditText alias = ui.field(box, "显示名称（留空恢复应用原名）", c.aliases.optString(key, "")); alias.setHint(label);
        ui.note(box, "显示颜色"); Spinner color = new Spinner(a);
        List<String> names = new ArrayList<>(); names.add("默认（按包名稳定分配）"); java.util.Collections.addAll(names, Palette.NAMES);
        ArrayAdapter<String> adapter = new ArrayAdapter<>(a, android.R.layout.simple_spinner_item, names); adapter.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item); color.setAdapter(adapter);
        color.setSelection(c.colors.has(key) ? Palette.IDS.indexOf(c.colors.optString(key)) + 1 : 0); box.addView(color, new LinearLayout.LayoutParams(-1, ui.dp(52)));
        AlertDialog dialog = new AlertDialog.Builder(a).setTitle("应用名称与颜色").setView(box).setPositiveButton("保存", null)
            .setNeutralButton("恢复此应用默认设置", (d,w) -> save(next -> { next.aliases.remove(key); next.colors.remove(key); })).setNegativeButton("取消", null).create();
        dialog.setOnShowListener(d -> dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(v -> {
            String name = packageInput.getText().toString().trim().toLowerCase(Locale.ROOT), display = alias.getText().toString().trim();
            if (name.isEmpty() || name.length() > 200 || name.contains(" ") || display.length() > 200) { a.toast("请填写有效包名，名称和包名最多 200 个字符"); return; }
            save(next -> {
                if (!key.isEmpty() && !key.equals(name)) { next.aliases.remove(key); next.colors.remove(key); }
                if (display.isEmpty()) next.aliases.remove(name); else next.aliases.put(name, display);
                if (color.getSelectedItemPosition() == 0) next.colors.remove(name); else next.colors.put(name, Palette.IDS.get(color.getSelectedItemPosition()-1));
            }); dialog.dismiss();
        })); dialog.show();
    }
    private void picker() {
        Map<String,String> apps = new LinkedHashMap<>();
        for (ResolveInfo info : a.getPackageManager().queryIntentActivities(new Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER), 0)) apps.put(info.activityInfo.packageName, info.loadLabel(a.getPackageManager()).toString());
        for (LedgerStore.Row row : agent.store.recent(agent.settings.get().scope, 500)) { String pkg = row.event().optString("process_name"); if (!pkg.isEmpty()) apps.putIfAbsent(pkg, agent.reader.label(pkg)); }
        List<Map.Entry<String,String>> all = new ArrayList<>(apps.entrySet()); all.sort(Comparator.comparing(Map.Entry::getValue));
        List<Map.Entry<String,String>> filtered = new ArrayList<>(all);
        LinearLayout box = ui.column(); box.setPadding(ui.dp(18), 0, ui.dp(18), 0); EditText search = ui.field(box, "搜索名称或包名", "");
        ArrayAdapter<String> adapter = new ArrayAdapter<>(a, android.R.layout.simple_list_item_1, new ArrayList<>()); for (var entry : filtered) adapter.add(entry.getValue() + "\n" + entry.getKey());
        ListView list = new ListView(a); list.setAdapter(adapter); box.addView(list, new LinearLayout.LayoutParams(-1, ui.dp(340)));
        AlertDialog dialog = new AlertDialog.Builder(a).setTitle("选择应用").setView(box).setNegativeButton("关闭", null).create();
        list.setOnItemClickListener((p,v,pos,id) -> { var entry = filtered.get(pos); dialog.dismiss(); edit(entry.getKey(), entry.getValue()); });
        search.addTextChangedListener(new TextWatcher() {
            @Override public void beforeTextChanged(CharSequence s, int st, int count, int after) {}
            @Override public void onTextChanged(CharSequence s, int st, int before, int count) {
                String q = s.toString().toLowerCase(Locale.ROOT); filtered.clear(); adapter.clear();
                for (var entry : all) if ((entry.getKey()+" "+entry.getValue()).toLowerCase(Locale.ROOT).contains(q)) { filtered.add(entry); adapter.add(entry.getValue()+"\n"+entry.getKey()); }
                adapter.notifyDataSetChanged();
            }
            @Override public void afterTextChanged(Editable e) {}
        }); dialog.show();
    }
    private interface Change { void apply(Config config) throws Exception; }
    private void save(Change change) {
        agent.collector.execute(() -> { try { Config next = agent.settings.get(); change.apply(next); if (next.configured()) next.validate(); agent.settings.save(next); agent.uploader.request(false, true); a.toast("已保存，将在联网后同步"); } catch (Exception e) { a.toast(Agent.message(e)); } });
    }
}
