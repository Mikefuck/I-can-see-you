package com.focusledger.android;

import android.os.Build;
import android.widget.CheckBox;
import android.widget.LinearLayout;
import android.widget.RadioButton;
import android.widget.RadioGroup;

final class KeepAlivePane {
    final MainActivity a; final Ui ui; final Agent agent;
    KeepAlivePane(MainActivity a) { this.a = a; ui = a.ui; agent = a.agent; }
    void build() {
        Config c = agent.settings.get(); LinearLayout strategy = ui.card(a.body); ui.title(strategy, "选择保活方案");
        ui.note(strategy, Build.MANUFACTURER + " " + Build.MODEL + " · Android " + Build.VERSION.RELEASE + (KeepAlive.isXiaomi() ? "\n已识别小米系设备，建议使用小米优化。" : ""));
        RadioGroup group = new RadioGroup(a);
        RadioButton xiaomi = mode("小米优化 · MIUI / 澎湃 OS", R.id.mode_xiaomi); group.addView(xiaomi);
        RadioButton standard = mode("通用安卓 · 其他品牌", R.id.mode_standard); group.addView(standard);
        group.check(c.mode.equals("xiaomi") ? R.id.mode_xiaomi : R.id.mode_standard); strategy.addView(group);
        ui.note(strategy, "两个模式共享前台服务、系统恢复任务、断点补采和离线队列。小米模式额外提供厂商设置入口及配置指引；切换不会更换设备身份或清空记录。");
        group.setOnCheckedChangeListener((g,id) -> agent.collector.execute(() -> {
            try { Config current = agent.settings.get(); agent.settings.appearance(id == R.id.mode_xiaomi ? "xiaomi" : "standard", current.theme); KeepAlive.schedule(a, agent.settings.wanted()); agent.updateNotification(); a.runOnUiThread(a::render); }
            catch (Exception e) { a.toast(Agent.message(e)); }
        }));
        LinearLayout common = ui.card(a.body); ui.title(common, "系统权限与后台运行");
        a.dynamic(common, "usage_permission", 14, false); common.addView(ui.button("设置使用情况访问权限", v -> KeepAlive.usageSettings(a)));
        a.dynamic(common, "battery_permission", 14, false); common.addView(ui.button("允许忽略电池优化", v -> KeepAlive.batterySettings(a)));
        a.dynamic(common, "notifications", 14, false); common.addView(ui.button("关闭 / 管理状态通知", v -> KeepAlive.notificationSettings(a)));
        ui.note(common, "开始采集不再自动申请通知权限。Android 13 及以上新安装默认不显示通知栏状态；旧版本已允许通知的用户，可点上方按钮手动关闭一次。Android 9–12 也需在系统设置中关闭。\n\n关闭状态通知后仍保留实时采集，系统仍可能在“正在运行的应用”等位置显示服务。暂停、上传和停止可在总览操作。此开关与音乐识别的通知访问权限不同。");
        common.addView(ui.button("打开应用信息与后台设置", v -> KeepAlive.appInfo(a)));
        if (c.mode.equals("xiaomi")) {
            LinearLayout vendor = ui.card(a.body); ui.title(vendor, "小米 / Redmi 专项设置");
            ui.note(vendor, "系统版本可能调整入口。下面的勾选仅表示你已手动确认，App 无法通过公开接口自动核验这些小米专属开关。");
            vendor.addView(ui.button("① 允许自启动", v -> KeepAlive.xiaomiAutostart(a))); manual(vendor, "xiaomi_autostart", "我已手动开启自启动");
            vendor.addView(ui.button("② 应用省电设为无限制", v -> KeepAlive.xiaomiBattery(a))); manual(vendor, "xiaomi_battery", "我已手动选择无限制");
            vendor.addView(ui.button("③ 后台锁定 / 最近任务锁定", v -> KeepAlive.xiaomiLock(a))); manual(vendor, "xiaomi_lock", "我已手动将应用加入后台锁定");
            if (!KeepAlive.isXiaomi()) ui.note(vendor, "当前不是小米系设备，专属入口会回到通用应用设置；采集和同步机制仍正常工作。");
        } else {
            LinearLayout other = ui.card(a.body); ui.title(other, "其他品牌的后台设置");
            ui.note(other, "三星：在电池设置中将本应用移出休眠和深度休眠列表。\n华为 / 荣耀：在应用启动管理中，允许自启动、关联启动和后台活动。\nOPPO / vivo / 一加 / realme：在应用电池与后台管理中允许后台活动和自启动。\n\n入口以系统实际显示为准；可以使用上面的应用信息入口查找。");
        }
        LinearLayout mechanism = ui.card(a.body); ui.title(mechanism, "运行方式与边界");
        ui.note(mechanism, "亮屏时每秒读取一次系统使用事件，每 30 秒分段保存。熄屏后降低采样频率，不持有永久唤醒锁；休眠时同步可能延迟，唤醒后恢复。\n\n系统任务通常至少间隔 15 分钟，受省电与系统调度影响。重启后需首次解锁；如果系统保留了使用事件，最多尝试补采中断后的最近 48 小时。未提供的历史不能保证补全。\n\n“强行停止”、撤销授权和系统极端省电仍会阻止运行。需要重新打开 App 或恢复权限。后台锁定主要防止一键清理，不等同于永不被杀。");
        LinearLayout health = ui.card(a.body); ui.title(health, "当前运行检查"); a.dynamic(health, "health", 13, false);
        health.addView(ui.button("刷新检查", v -> a.render()));
        health.addView(ui.button("复制不含密钥的诊断信息", v -> {
            String info = "FocusLedger Android " + Config.VERSION + "\n" + Build.MANUFACTURER + " " + Build.MODEL + " Android " + Build.VERSION.RELEASE
                + "\nmode=" + agent.settings.get().mode + " usage=" + UsageReader.permitted(a) + " batteryExempt=" + KeepAlive.batteryExempt(a)
                + " notifications=" + KeepAlive.notifications(a) + " service=" + (agent.service != null) + " tracking=" + agent.settings.tracking()
                + "\nlastCapture=" + Ui.clock(MainActivity.longValue(agent.store.get("last_capture", "0"))) + "\n" + agent.store.get("recovery_note", "") + "\n" + agent.captureNote;
            a.getSystemService(android.content.ClipboardManager.class).setPrimaryClip(android.content.ClipData.newPlainText("专注记录诊断", info)); a.toast("诊断信息已复制，不包含上传密钥或使用记录");
        }));
    }
    private RadioButton mode(String label, int id) {
        RadioButton radio = new RadioButton(a); radio.setId(id); radio.setText(label); radio.setTextColor(ui.ink); radio.setTextSize(14);
        radio.setMinHeight(ui.dp(56)); radio.setPadding(ui.dp(8), ui.dp(10), ui.dp(8), ui.dp(10)); ui.tint(radio);
        android.graphics.drawable.StateListDrawable background = new android.graphics.drawable.StateListDrawable();
        background.addState(new int[]{android.R.attr.state_checked}, ui.ripple(ui.accentSoft, 0, 14));
        background.addState(new int[]{}, ui.ripple(0, 0, 14)); radio.setBackground(background);
        radio.setLayoutParams(new android.widget.RadioGroup.LayoutParams(-1, -2)); return radio;
    }
    private void manual(LinearLayout parent, String key, String text) {
        CheckBox check = new CheckBox(a); check.setText(text); check.setTextColor(ui.muted); check.setTextSize(13); check.setMinHeight(ui.dp(48));
        ui.tint(check); check.setChecked(agent.settings.prefs.getBoolean(key, false)); check.setOnCheckedChangeListener((b,value) -> agent.settings.prefs.edit().putBoolean(key, value).apply()); parent.addView(check);
    }
}
