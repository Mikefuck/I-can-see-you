package com.focusledger.android;

import android.os.SystemClock;
import org.json.JSONArray;
import org.json.JSONObject;
import java.util.List;
import java.util.Map;

final class Management {
    record Session(String endpoint, String cookie, String csrf, long accountId, String username, boolean admin, long until) {}
    private final Agent agent;
    volatile Session session;
    volatile Config loginConfig;
    Management(Agent agent) { this.agent = agent; }
    Session current() { Session s = session; if (s != null && s.until < SystemClock.elapsedRealtime()) session = s = null; return s; }
    JSONObject login(Config c, String username, String password) throws Exception {
        if (username.trim().isEmpty() || password.isEmpty()) throw new IllegalArgumentException("请填写用户名和密码");
        session = null; Exception last = null;
        for (String endpoint : c.endpoints()) {
            try {
                Transport.Reply reply = agent.transport.at(endpoint, "POST", "/api/v1/management/login", new JSONObject().put("username", username.trim()).put("password", password), null, null, null, false, 8000);
                String cookie = cookies(reply.headers(), endpoint); JSONObject body = reply.json();
                if (cookie.isEmpty() || body.optString("csrf").isEmpty()) throw new IllegalStateException("服务器没有返回管理会话");
                session = new Session(endpoint, cookie, body.getString("csrf"), body.getLong("account_id"), body.getString("username"), body.getBoolean("is_admin"), SystemClock.elapsedRealtime()+12*3600000L);
                loginConfig = c.copy(); return body;
            } catch (Transport.ApiError e) { if (e.status < 500) throw e; last = e; }
            catch (java.io.IOException e) { last = e; }
        }
        if (last instanceof Transport.ApiError) throw last;
        throw new java.io.IOException("无法登录，请检查地址、网络和 HTTPS 证书");
    }
    JSONObject request(String method, String path, JSONObject body) throws Exception {
        Session s = current(); if (s == null) throw new IllegalStateException("请先登录服务端");
        try { return agent.transport.at(s.endpoint, method, "/api/v1/management"+path, body, null, s.cookie, s.csrf, false, 8000).json(); }
        catch (Transport.ApiError e) { if (e.status == 401 || e.status == 403) session = null; throw e; }
    }
    void logout() throws Exception { try { if (current() != null) request("POST", "/logout", new JSONObject()); } finally { session = null; loginConfig = null; } }
    JSONArray users() throws Exception { return request("GET", "/users", null).getJSONArray("users"); }
    private String cookies(Map<String, List<String>> headers, String endpoint) {
        StringBuilder cookies = new StringBuilder();
        for (Map.Entry<String,List<String>> header : headers.entrySet()) if (header.getKey() != null && header.getKey().equalsIgnoreCase("Set-Cookie")) {
            for (String value : header.getValue()) {
                if (value.toLowerCase(java.util.Locale.ROOT).contains("; secure") && !endpoint.startsWith("https://")) throw new IllegalStateException("服务端要求安全 Cookie，请使用 HTTPS 地址登录");
                if (cookies.length() > 0) cookies.append("; "); cookies.append(value.split(";", 2)[0]);
            }
        }
        return cookies.toString();
    }
}
