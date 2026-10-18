package com.focusledger.android;

import android.content.Context;
import android.content.SharedPreferences;
import org.json.JSONObject;

/** Each home-screen instance keeps its own filters, page, theme and encrypted read grant. */
final class WidgetStore {
    static final class Options {
        String primary = "", fallback = "", mode = "public", user = "", device = "", theme = "system", token = "", account = "";
        double expires;
        boolean configured;
        String identity() { return primary + "|" + fallback + "|" + mode + "|" + Config.sha256(token); }
    }
    private final SharedPreferences prefs;
    WidgetStore(Context context) { prefs = context.getSharedPreferences("ledger_widgets", Context.MODE_PRIVATE); }
    Options options(int id) {
        Options o = new Options();
        try {
            JSONObject j = new JSONObject(prefs.getString("options_" + id, "{}"));
            o.primary = j.optString("primary"); o.fallback = j.optString("fallback"); o.mode = j.optString("mode", "public");
            o.user = j.optString("user"); o.device = j.optString("device"); o.theme = j.optString("theme", "system");
            o.account = j.optString("account"); o.expires = j.optDouble("expires", 0); o.configured = j.optBoolean("configured");
            o.token = SecretStore.decrypt(j.optString("token"));
        } catch (Exception ignored) { o.token = ""; }
        return o;
    }
    synchronized void save(int id, Options o) throws Exception {
        synchronized (WidgetStore.class) {
            JSONObject j = new JSONObject().put("primary", o.primary).put("fallback", o.fallback).put("mode", o.mode)
                .put("user", o.user).put("device", o.device).put("theme", o.theme).put("token", SecretStore.encrypt(o.token))
                .put("account", o.account).put("expires", o.expires).put("configured", true);
            if (!prefs.edit().putString("options_" + id, j.toString()).remove("data_" + id).remove("error_" + id)
                    .remove("at_" + id).remove("page_" + id).commit()) throw new IllegalStateException("无法保存小组件设置");
        }
    }
    JSONObject data(int id) {
        Options o = options(id);
        if (o.mode.equals("members") && (o.token.isEmpty() || o.expires <= System.currentTimeMillis() / 1000d)) {
            failure(id, o.identity(), "授权已失效 · 点击设置重新授权", true); return null;
        }
        try { String raw = prefs.getString("data_" + id, ""); return raw.isEmpty() ? null : new JSONObject(raw); }
        catch (Exception ignored) { return null; }
    }
    synchronized void success(int id, String identity, JSONObject data) {
        success(id, identity, data, System.currentTimeMillis());
    }
    synchronized void success(int id, String identity, JSONObject data, long at) {
        synchronized (WidgetStore.class) {
            if (!options(id).identity().equals(identity)) return;
            prefs.edit().putString("data_" + id, data.toString()).putLong("at_" + id, at)
                .remove("error_" + id).apply();
        }
    }
    synchronized void failure(int id, String identity, String error, boolean clear) {
        synchronized (WidgetStore.class) {
            if (!options(id).identity().equals(identity)) return;
            SharedPreferences.Editor edit = prefs.edit().putString("error_" + id, error);
            if (clear) edit.remove("data_" + id).remove("at_" + id);
            edit.apply();
        }
    }
    String error(int id) { return prefs.getString("error_" + id, ""); }
    long updated(int id) { return prefs.getLong("at_" + id, 0); }
    int page(int id) { return Math.max(0, prefs.getInt("page_" + id, 0)); }
    void page(int id, int value) { prefs.edit().putInt("page_" + id, Math.max(0, value)).apply(); }
    void delete(int id) {
        synchronized (WidgetStore.class) {
            SharedPreferences.Editor e = prefs.edit();
            for (String prefix : new String[]{"options_", "data_", "error_", "at_", "page_"}) e.remove(prefix + id);
            e.apply();
        }
    }
}
