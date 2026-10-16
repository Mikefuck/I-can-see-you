package com.focusledger.android;

import android.text.InputType;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.Switch;

final class ConnectionPane {
    final MainActivity a; final Ui ui; final Agent agent;
    ConnectionPane(MainActivity a) { this.a = a; ui = a.ui; agent = a.agent; }
    void build() {
        Config c = agent.settings.get();
        if (agent.settings.prefs.contains("draft_key")) {
            try { c.apiKey = SecretStore.decrypt(agent.settings.prefs.getString("draft_key", "")); c.primary = agent.settings.prefs.getString("draft_primary", c.primary); c.fallback = agent.settings.prefs.getString("draft_fallback", c.fallback); }
            catch (Exception e) { a.toast("未验证的密钥草稿无法读取，请重新生成密钥"); }
        }
        LinearLayout server = ui.card(a.body); ui.title(server, "连接你的服务器");
        if (agent.settings.prefs.contains("draft_key")) ui.note(server, "已填入新生成的密钥草稿，验证保存后生效。");
        ui.note(server, "填写完整地址。公网与内网两个地址须指向同一个服务端；连接失败时自动尝试另一个地址。");
        EditText primary = ui.field(server, "主地址", c.primary, InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI); primary.setHint("https://example.com");
        EditText fallback = ui.field(server, "备用地址（可留空）", c.fallback, InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI); fallback.setHint("http://192.168.1.10:8080");
        EditText key = ui.field(server, "上传密钥", c.apiKey, InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD);
        ui.note(server, "也可以在“服务端”页登录账户，生成密钥并自动接入。密钥由 Android Keystore 加密保存。");
        EditText name = ui.field(server, "设备名称", c.deviceName);
        LinearLayout sampling = ui.card(a.body); ui.title(sampling, "采集与上传");
        EditText interval = ui.field(sampling, "上传间隔 / 秒（10–300）", ""+c.uploadSeconds, InputType.TYPE_CLASS_NUMBER);
        Switch change = ui.toggle(sampling, "应用切换时立即上传", c.uploadOnChange);
        Switch battery = ui.toggle(sampling, "记录电量和充电状态", c.batteryEnabled);
        EditText batteryInterval = ui.field(sampling, "电池记录间隔 / 秒（30–3600）", ""+c.batterySeconds, InputType.TYPE_CLASS_NUMBER);
        Switch suspend = ui.toggle(sampling, "熄屏时尝试上传", c.uploadOnSuspend);
        Switch shutdown = ui.toggle(sampling, "关机时尝试上传", c.uploadOnShutdown);
        Switch boot = ui.toggle(sampling, "重启并解锁后自动恢复", c.bootEnabled);
        ui.note(sampling, "安卓使用屏幕与锁屏状态停止计时。其他应用的触摸活动不向普通 App 开放，因此不使用电脑端的键鼠空闲阈值。关机时来不及上传的记录会保留补传。");
        a.body.addView(ui.primary("验证连接并保存", v -> {
            try {
                Config next = agent.settings.get(); next.primary = primary.getText().toString().trim(); next.fallback = fallback.getText().toString().trim();
                next.apiKey = key.getText().toString().trim(); next.deviceName = name.getText().toString().trim();
                next.uploadSeconds = Integer.parseInt(interval.getText().toString()); next.batterySeconds = Integer.parseInt(batteryInterval.getText().toString());
                next.uploadOnChange = change.isChecked(); next.batteryEnabled = battery.isChecked(); next.uploadOnSuspend = suspend.isChecked();
                next.uploadOnShutdown = shutdown.isChecked(); next.bootEnabled = boot.isChecked(); next.validate();
                a.verifyAndSave(next, a::render);
            } catch (Exception e) { a.toast(Agent.message(e)); }
        }));
        ui.note(a.body, "首次接入、修改地址、密钥或设备名称需要联网验证。已验证的连接可离线调整采集选项。");
        LinearLayout rules = ui.card(a.body); ui.title(rules, "应用名称与颜色");
        ui.note(rules, "按应用包名设置显示名称和 12 种预设配色。保存后也会同步服务端已有历史记录。");
        rules.addView(ui.button("管理应用名称与颜色", v -> new AppRulesPane(a).show()));
        LinearLayout cache = ui.card(a.body); ui.title(cache, "本机缓存");
        ui.note(cache, "不同服务器和账户的队列分别保留。切回原来的主地址和账户后，可继续补传旧队列。卸载 App 会删除本机缓存。");
        cache.addView(ui.quiet("清除当前连接的待上传记录", v -> a.confirm("清除待上传记录", "仅清除当前连接尚未上传的记录，无法撤销。其他连接和服务端记录不会被清除。", () -> {
            agent.collector.execute(() -> { agent.store.clearPending(agent.settings.get().scope); a.toast("已清除当前连接的待上传记录"); });
        })));
    }
}
