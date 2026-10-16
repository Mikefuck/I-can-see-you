package com.focusledger.android;

import android.content.Context;
import android.content.SharedPreferences;
import org.json.JSONObject;
import java.util.UUID;

final class Settings {
    final SharedPreferences prefs;
    private volatile Config config;
    volatile String warning = "";
    Settings(Context context) {
        prefs = context.getSharedPreferences("focusledger", Context.MODE_PRIVATE);
        try {
            config = new Config(new JSONObject(prefs.getString("config", "{}")));
            config.apiKey = SecretStore.decrypt(prefs.getString("upload_key", ""));
        } catch (Exception e) {
            config = new Config(); warning = "本机密钥无法读取，请重新填写连接信息。已有队列保留。";
        }
    }
    Config get() { return config.copy(); }
    boolean wanted() { return prefs.getBoolean("service_wanted", false); }
    boolean tracking() { return prefs.getBoolean("tracking", false); }
    void intent(boolean wanted, boolean tracking) {
        SharedPreferences.Editor edit = prefs.edit().putBoolean("service_wanted", wanted).putBoolean("tracking", tracking);
        if (!tracking && tracking()) edit.putLong("idle_since", System.currentTimeMillis());
        if (!edit.commit()) throw new IllegalStateException("无法保存采集状态");
    }
    synchronized Config bind(Config candidate, JSONObject checked) throws Exception {
        Config c = candidate.copy(); c.accountId = checked.getLong("account_id"); c.username = checked.getString("username");
        c.scope = Config.sha256(c.primary + "|" + c.accountId);
        JSONObject bindings = new JSONObject(prefs.getString("bindings", "{}"));
        JSONObject profile = bindings.optJSONObject(c.scope);
        c.deviceId = profile == null ? UUID.randomUUID().toString() : profile.getString("deviceId");
        if (!c.scope.equals(config.scope)) {
            c.aliases = profile == null ? new JSONObject() : profile.optJSONObject("aliases");
            c.colors = profile == null ? new JSONObject() : profile.optJSONObject("colors");
            if (c.aliases == null) c.aliases = new JSONObject(); if (c.colors == null) c.colors = new JSONObject();
        }
        c.features.clear();
        org.json.JSONArray features = checked.optJSONArray("features");
        if (features != null) for (int i = 0; i < features.length(); i++) c.features.add(features.getString(i));
        return c;
    }
    synchronized void save(Config c) throws Exception {
        String encrypted = SecretStore.encrypt(c.apiKey);
        JSONObject bindings = new JSONObject(prefs.getString("bindings", "{}"));
        if (!c.scope.isEmpty()) bindings.put(c.scope, new JSONObject().put("deviceId", c.deviceId).put("aliases", c.aliases).put("colors", c.colors));
        if (!prefs.edit().putString("config", c.json().toString()).putString("upload_key", encrypted).putString("bindings", bindings.toString()).commit())
            throw new IllegalStateException("无法保存连接设置");
        config = c.copy(); warning = "";
    }
    synchronized void appearance(String mode, String theme) throws Exception {
        Config c = get(); c.mode = mode; c.theme = theme; save(c);
    }
}
