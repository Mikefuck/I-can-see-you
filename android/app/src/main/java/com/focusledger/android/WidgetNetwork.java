package com.focusledger.android;

import org.json.JSONObject;
import java.time.ZoneId;
import java.util.ArrayList;
import java.util.List;

/** Never sends the upload key. Failover is limited to the two explicitly configured origins. */
final class WidgetNetwork {
    private final Transport transport = new Transport("");
    private List<String> endpoints(WidgetStore.Options o) {
        List<String> result = new ArrayList<>(); result.add(Config.normalizeUrl(o.primary));
        if (!o.fallback.isEmpty() && !o.fallback.equals(o.primary)) result.add(Config.normalizeUrl(o.fallback));
        return result;
    }
    JSONObject fetch(WidgetStore.Options o) throws Exception {
        if (o.mode.equals("members") && o.token.isEmpty()) throw new IllegalStateException("请在设置中重新授权");
        String path = (o.mode.equals("members") ? "/api/v1/widget/board" : "/api/web/board")
            + "?since=" + (long)WidgetData.dayStart(System.currentTimeMillis() / 1000d, ZoneId.systemDefault());
        return request(o, "GET", path, null).json();
    }
    private Transport.Reply request(WidgetStore.Options o, String method, String path, JSONObject body) throws Exception {
        Exception last = null;
        for (String endpoint : endpoints(o)) {
            try { return transport.at(endpoint, method, path, body, o.mode.equals("members") ? o.token : null, null, null, false, 6000); }
            catch (Transport.ApiError e) { if (e.status < 500) throw e; last = e; }
            catch (java.io.IOException e) { last = e; }
        }
        throw last == null ? new java.io.IOException("无法连接服务器") : last;
    }
    void authorize(WidgetStore.Options o, String username, String password) throws Exception {
        if (username.trim().isEmpty() || password.isEmpty()) throw new IllegalArgumentException("请填写用户名和密码");
        Exception last = null;
        for (String endpoint : endpoints(o)) {
            String cookie = "", csrf = "";
            try {
                Transport.Reply login = transport.at(endpoint, "POST", "/api/v1/management/login",
                    new JSONObject().put("username", username.trim()).put("password", password), null, null, null, false, 6000);
                cookie = Management.cookies(login.headers(), endpoint); csrf = login.json().getString("csrf");
                JSONObject grant = transport.at(endpoint, "POST", "/api/v1/management/widget-token", new JSONObject(),
                    null, cookie, csrf, false, 6000).json();
                if (!"widget:board:read".equals(grant.getString("scope")) || grant.getString("token").length() < 32)
                    throw new IllegalStateException("服务端小组件授权无效");
                o.token = grant.getString("token"); o.account = grant.getString("username"); o.expires = grant.getDouble("expires_at");
                return;
            } catch (Transport.ApiError e) { if (e.status < 500) throw e; last = e; }
            catch (java.io.IOException e) { last = e; }
            finally {
                if (!cookie.isEmpty()) try { transport.at(endpoint, "POST", "/api/v1/management/logout", new JSONObject(), null, cookie, csrf, false, 2000); }
                catch (Exception ignored) { /* The temporary login also expires server-side after 12 hours. */ }
            }
        }
        throw last == null ? new java.io.IOException("无法授权，请检查服务器地址") : last;
    }
    void revoke(WidgetStore.Options o) throws Exception {
        if (o.token.isEmpty()) return;
        try { request(o, "POST", "/api/v1/widget/revoke", new JSONObject()); }
        catch (Transport.ApiError e) { if (e.status != 401) throw e; }
    }
    static String message(Exception e) {
        if (e instanceof Transport.ApiError api) return switch (api.status) {
            case 401, 403 -> "授权已失效 · 点击设置重新授权";
            case 404 -> "请先升级服务端到 r13";
            default -> "服务端暂不可用 · 点击刷新重试";
        };
        if (e instanceof IllegalStateException || e instanceof IllegalArgumentException) return e.getMessage();
        return "网络不可用 · 点击刷新重试";
    }
}
