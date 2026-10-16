package com.focusledger.android;

import android.content.Context;
import android.provider.Settings;
import org.json.JSONObject;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.zip.GZIPOutputStream;

final class Transport {
    static final class ApiError extends IOException {
        final int status; final JSONObject response;
        ApiError(int status, JSONObject body) {
            super(message(status, body)); this.status = status; response = body;
        }
        private static String message(int code, JSONObject body) {
            JSONObject detail = body.optJSONObject("detail");
            if (code == 409 && detail != null && "device_name_conflict".equals(detail.optString("code"))) return "设备名称已被占用，请修改名称后重试";
            return switch (code) {
                case 401 -> "密钥无效、会话过期或账户已停用";
                case 403 -> "没有此操作的权限，或管理会话已失效";
                case 409 -> "设备身份、用户名或记录发生冲突";
                case 413 -> "服务端或代理限制了上传包大小";
                case 422 -> "数据未通过校验，请检查输入和手机日期时间";
                case 429 -> "请求过于频繁，请稍后重试";
                default -> "服务器返回 HTTP " + code;
            };
        }
    }
    record Reply(JSONObject json, String endpoint, Map<String, List<String>> headers) {}
    private final String machineId;
    private final Map<String, String> preferred = new ConcurrentHashMap<>();
    private final Map<String, Boolean> gzip = new ConcurrentHashMap<>();
    Transport(String machineId) { this.machineId = machineId; }
    Transport(Context context) {
        String id = Settings.Secure.getString(context.getContentResolver(), Settings.Secure.ANDROID_ID);
        machineId = id == null || id.isEmpty() ? "" : Config.sha256("FocusLedger/android/v1|" + id);
    }
    Reply request(Config config, String method, String path, JSONObject body) throws Exception {
        List<String> endpoints = new ArrayList<>(config.endpoints());
        String saved = preferred.get(config.scope); if (saved != null && endpoints.remove(saved)) endpoints.add(0, saved);
        Exception last = null;
        for (String endpoint : endpoints) {
            try {
                Reply result;
                try { result = at(endpoint, method, path, body, config.apiKey, null, null, gzip.getOrDefault(endpoint, false), endpoints.size() > 1 ? 3500 : 8000); }
                catch (ApiError e) {
                    if (gzip.getOrDefault(endpoint, false) && (e.status == 400 || e.status == 415)) {
                        gzip.put(endpoint, false); result = at(endpoint, method, path, body, config.apiKey, null, null, false, 8000);
                    } else throw e;
                }
                preferred.put(config.scope, endpoint);
                org.json.JSONArray encodings = result.json.optJSONArray("upload_encodings");
                if (encodings != null) for (int i = 0; i < encodings.length(); i++) if ("gzip".equals(encodings.optString(i))) gzip.put(endpoint, true);
                return result;
            } catch (ApiError e) { if (e.status < 500) throw e; last = e; }
            catch (IOException e) { last = e; }
        }
        if (last instanceof ApiError) throw last;
        throw new IOException(endpoints.size() > 1 ? "两个地址均无法连接，请检查网络、地址及 HTTPS 证书" : "无法连接服务器，请检查网络、地址及 HTTPS 证书");
    }
    JSONObject check(Config config) throws Exception {
        JSONObject j = request(config, "GET", "/api/v1/agent/check", null).json;
        if (!j.optBoolean("ok") || j.optInt("schema_version") != 1 || j.optLong("account_id") <= 0 || j.optString("username").isEmpty())
            throw new IOException("服务端协议不兼容");
        return j;
    }
    String activeUrl(Config c) { return preferred.getOrDefault(c.scope, c.primary); }

    Reply at(String endpoint, String method, String path, JSONObject body, String apiKey, String cookie, String csrf, boolean compress, int timeout) throws Exception {
        HttpURLConnection connection = (HttpURLConnection) new URL(endpoint + path).openConnection();
        connection.setInstanceFollowRedirects(false); connection.setConnectTimeout(timeout); connection.setReadTimeout(timeout);
        connection.setRequestMethod(method); connection.setRequestProperty("Accept", "application/json");
        connection.setRequestProperty("User-Agent", "FocusLedger-Android/" + Config.VERSION);
        if (apiKey != null && !apiKey.isEmpty()) connection.setRequestProperty("Authorization", "Bearer " + apiKey);
        if (cookie != null) connection.setRequestProperty("Cookie", cookie);
        if (csrf != null) connection.setRequestProperty("X-CSRF-Token", csrf);
        if (path.startsWith("/api/v1/management/")) connection.setRequestProperty("X-FocusLedger-Client", "desktop");
        if (!machineId.isEmpty() && (path.equals("/api/v1/usage/batches") || path.startsWith("/api/v1/agent/app-")))
            connection.setRequestProperty("X-FocusLedger-Machine-ID", machineId);
        try {
            if (body != null) {
                byte[] bytes = body.toString().getBytes(StandardCharsets.UTF_8);
                if (bytes.length > 2 * 1024 * 1024) throw new IOException("上传包超过协议大小限制");
                if (compress && bytes.length >= 256) {
                    ByteArrayOutputStream zipped = new ByteArrayOutputStream();
                    try (GZIPOutputStream out = new GZIPOutputStream(zipped)) { out.write(bytes); }
                    if (zipped.size() < bytes.length) { bytes = zipped.toByteArray(); connection.setRequestProperty("Content-Encoding", "gzip"); }
                }
                connection.setDoOutput(true); connection.setRequestProperty("Content-Type", "application/json; charset=utf-8");
                connection.setFixedLengthStreamingMode(bytes.length);
                try (java.io.OutputStream out = connection.getOutputStream()) { out.write(bytes); }
            }
            int status = connection.getResponseCode();
            if (status >= 300 && status < 400) throw new ApiError(status, new JSONObject());
            InputStream source = status < 400 ? connection.getInputStream() : connection.getErrorStream();
            ByteArrayOutputStream data = new ByteArrayOutputStream();
            if (source != null) try (InputStream in = source) {
                byte[] buffer = new byte[8192]; int count;
                while ((count = in.read(buffer)) != -1) {
                    if (data.size() + count > 1024 * 1024) throw new IOException("服务端响应过大");
                    data.write(buffer, 0, count);
                }
            }
            JSONObject json;
            try { json = new JSONObject(data.toString(StandardCharsets.UTF_8.name())); }
            catch (Exception e) { if (status >= 400) json = new JSONObject(); else throw new IOException("服务器没有返回有效 JSON"); }
            if (status >= 400) throw new ApiError(status, json);
            return new Reply(json, endpoint, connection.getHeaderFields());
        } finally { connection.disconnect(); }
    }
}
