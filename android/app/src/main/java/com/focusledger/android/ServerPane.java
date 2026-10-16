package com.focusledger.android;

import android.app.AlertDialog;
import android.text.InputType;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.Switch;
import org.json.JSONArray;
import org.json.JSONObject;

final class ServerPane {
    final MainActivity a; final Ui ui; final Agent agent;
    ServerPane(MainActivity a) { this.a = a; ui = a.ui; agent = a.agent; }
    void build() {
        Management.Session session = agent.management.current(); Config c = agent.settings.get();
        LinearLayout account = ui.card(a.body); ui.title(account, "服务端账户");
        ui.note(account, "此处使用账户密码登录；上传密钥不能用于管理。密码和管理会话只保存在内存，关闭进程后需要重新登录。");
        if (session == null) {
            EditText primary = ui.field(account, "服务端主地址", c.primary, InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
            EditText fallback = ui.field(account, "备用地址（可留空）", c.fallback, InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
            EditText username = ui.field(account, "用户名", c.username);
            EditText password = ui.field(account, "密码", "", InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD);
            account.addView(ui.primary("登录", v -> {
                Config login = c.copy();
                try { login.primary = Config.normalizeUrl(primary.getText().toString()); login.fallback = fallback.getText().toString().trim().isEmpty() ? "" : Config.normalizeUrl(fallback.getText().toString()); }
                catch (Exception e) { a.toast(Agent.message(e)); return; }
                String name = username.getText().toString(), secret = password.getText().toString();
                a.io(() -> agent.management.login(login, name, secret), result -> { password.setText(""); if (a.selected == 4) a.render(); });
            }));
        } else {
            account.addView(ui.text(session.username() + (session.admin() ? " · 管理员" : " · 成员"), 20, true)); ui.note(account, session.endpoint());
            account.addView(ui.button("生成上传密钥并自动接入", v -> a.confirm("生成新的上传密钥", "旧密钥将立即失效。其他使用同一账户的客户端也需要更新密钥。确认后会验证连接并将新密钥保存到本机。", () -> {
                a.io(() -> {
                    JSONObject token = agent.management.request("POST", "/token", new JSONObject());
                    Config next = agent.management.loginConfig.copy(); next.apiKey = token.getString("api_key"); next.deviceName = agent.settings.get().deviceName;
                    return next;
                }, next -> {
                    try { agent.settings.prefs.edit().putString("draft_key", SecretStore.encrypt(next.apiKey)).putString("draft_primary", next.primary).putString("draft_fallback", next.fallback).commit(); }
                    catch (Exception e) { a.toast("新密钥尚未保存，请点击复制密钥备份"); }
                    // Keep the rotated key recoverable even if subsequent device registration fails.
                    new AlertDialog.Builder(a).setTitle("新上传密钥已生成").setMessage("新密钥已作为加密草稿填入连接页。可先复制备用；验证接入失败时，草稿仍会保留供你重试。")
                        .setPositiveButton("保存并接入", (d,w) -> a.verifyAndSave(next, () -> a.show(2)))
                        .setNeutralButton("复制密钥", (d,w) -> {
                            a.getSystemService(android.content.ClipboardManager.class).setPrimaryClip(android.content.ClipData.newPlainText("FocusLedger 上传密钥", next.apiKey));
                            a.verifyAndSave(next, () -> a.show(2));
                        }).setNegativeButton("仅填入连接页", (d,w) -> fillToken(next)).show();
                });
            })));
            account.addView(ui.button("退出管理登录", v -> a.io(() -> { agent.management.logout(); return true; }, done -> { if (a.selected == 4) a.render(); })));
            if (session.admin()) admin();
        }
        LinearLayout web = ui.card(a.body); ui.title(web, "看板、历史与账户设置");
        ui.note(web, "在 App 内打开现有服务端网页，查看公开 / 成员设备、日 / 周 / 月 / 年时间线、应用排行、公开范围和修改密码。网页登录与上面的管理登录独立。");
        web.addView(ui.button("打开完整服务端网页", v -> {
            Management.Session s = agent.management.current(); a.openBoard(s == null ? null : s.endpoint());
        }));
        ui.note(a.body, "端口映射、HTTPS 证书和 Docker 部署仍在服务器侧管理。");
    }
    private void fillToken(Config c) {
        // Persist only a draft encrypted key, never mark an unverified account as configured.
        try {
            agent.settings.prefs.edit().putString("draft_key", SecretStore.encrypt(c.apiKey)).putString("draft_primary", c.primary).putString("draft_fallback", c.fallback).apply();
            a.show(2);
        } catch (Exception e) { a.toast(Agent.message(e)); }
    }
    private void admin() {
        LinearLayout retention = ui.card(a.body); ui.title(retention, "数据保留期限");
        EditText days = ui.field(retention, "保留天数（1–365）", "", InputType.TYPE_CLASS_NUMBER);
        a.io(() -> agent.management.request("GET", "/settings", null), result -> { if (days.isAttachedToWindow()) days.setText(""+result.optInt("retention_days", 365)); });
        ui.note(retention, "缩短期限后，服务端会立即删除超期记录。");
        retention.addView(ui.button("保存保留期限", v -> {
            int value;
            try { value = Integer.parseInt(days.getText().toString()); if (value < 1 || value > 365) throw new NumberFormatException(); }
            catch (Exception e) { a.toast("请输入 1–365 之间的整数"); return; }
            a.confirm("修改数据保留期限", "服务端将保留最近 " + value + " 天；超过该期限的数据会立即清理，无法撤销。", () -> a.io(() -> agent.management.request("PUT", "/settings", new JSONObject().put("retention_days", value)), result -> a.toast("保留期限已保存")));
        }));
        LinearLayout members = ui.card(a.body); ui.title(members, "成员管理");
        members.addView(ui.button("创建成员", v -> createUser())); LinearLayout list = ui.column(); members.addView(list);
        members.addView(ui.button("刷新成员列表", v -> loadUsers(list))); loadUsers(list);
    }
    private void loadUsers(LinearLayout list) {
        a.io(() -> agent.management.users(), users -> {
            if (!list.isAttachedToWindow()) return; list.removeAllViews();
            for (int i = 0; i < users.length(); i++) {
                JSONObject user = users.optJSONObject(i); if (user == null) continue;
                long id = user.optLong("id"); boolean enabled = user.optBoolean("enabled"); String username = user.optString("username");
                LinearLayout row = ui.column(); Switch state = ui.toggle(row, username + (user.optBoolean("is_admin") ? " · 管理员" : ""), enabled);
                Management.Session session = agent.management.current(); if (session == null || session.accountId() == id) state.setEnabled(false);
                state.setOnCheckedChangeListener((button,value) -> {
                    button.setChecked(enabled);
                    a.confirm(value ? "启用成员" : "停用成员", value ? "启用 " + username + "？" : "停用 " + username + " 会注销其会话并使上传密钥失效。", () -> a.io(() -> agent.management.request("PATCH", "/users/"+id, new JSONObject().put("enabled", value)), result -> loadUsers(list)));
                });
                list.addView(row);
            }
        });
    }
    private void createUser() {
        LinearLayout box = ui.column(); box.setPadding(ui.dp(18), 0, ui.dp(18), ui.dp(10));
        EditText username = ui.field(box, "用户名（3–40 位英文、数字、下划线等）", "");
        EditText password = ui.field(box, "密码（12–256 个字符）", "", InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD);
        Switch admin = ui.toggle(box, "授予管理员权限", false);
        AlertDialog dialog = new AlertDialog.Builder(a).setTitle("创建成员").setView(box).setPositiveButton("创建", null).setNegativeButton("取消", null).create();
        dialog.setOnShowListener(d -> dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(v -> {
            String name = username.getText().toString().trim(), secret = password.getText().toString();
            if (!name.matches("[A-Za-z0-9_.-]{3,40}") || secret.length() < 12 || secret.length() > 256) { a.toast("请检查用户名和密码长度"); return; }
            a.io(() -> agent.management.request("POST", "/users", new JSONObject().put("username", name).put("password", secret).put("is_admin", admin.isChecked())), result -> { password.setText(""); dialog.dismiss(); if (a.selected == 4) a.render(); });
        })); dialog.show();
    }
}
