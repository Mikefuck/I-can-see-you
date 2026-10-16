package com.focusledger.android;

import android.os.Build;
import org.json.JSONArray;
import org.json.JSONObject;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.UUID;

public final class Config {
    public static final String VERSION = "0.1.2";
    public String primary = "", fallback = "", apiKey = "", deviceName = Build.MODEL;
    public String deviceId = UUID.randomUUID().toString(), scope = "", username = "";
    public String mode = KeepAlive.isXiaomi() ? "xiaomi" : "standard", theme = "system";
    public long accountId;
    public int uploadSeconds = 30, batterySeconds = 300;
    public boolean batteryEnabled = true, uploadOnChange = true, uploadOnSuspend = true;
    public boolean uploadOnShutdown = true, bootEnabled = true;
    public JSONObject aliases = new JSONObject(), colors = new JSONObject();
    public List<String> features = new ArrayList<>();

    public Config() {}

    public Config(JSONObject j) {
        primary = j.optString("primary", ""); fallback = j.optString("fallback", "");
        deviceName = j.optString("deviceName", Build.MODEL);
        deviceId = j.optString("deviceId", deviceId); scope = j.optString("scope", "");
        username = j.optString("username", ""); accountId = j.optLong("accountId");
        mode = j.optString("mode", mode); theme = j.optString("theme", "system");
        uploadSeconds = j.optInt("uploadSeconds", 30); batterySeconds = j.optInt("batterySeconds", 300);
        batteryEnabled = j.optBoolean("batteryEnabled", true); uploadOnChange = j.optBoolean("uploadOnChange", true);
        uploadOnSuspend = j.optBoolean("uploadOnSuspend", true); uploadOnShutdown = j.optBoolean("uploadOnShutdown", true);
        bootEnabled = j.optBoolean("bootEnabled", true);
        if (j.optJSONObject("aliases") != null) aliases = j.optJSONObject("aliases");
        if (j.optJSONObject("colors") != null) colors = j.optJSONObject("colors");
        JSONArray f = j.optJSONArray("features");
        if (f != null) for (int i = 0; i < f.length(); i++) features.add(f.optString(i));
    }

    public Config copy() {
        Config c = new Config(json()); c.apiKey = apiKey; return c;
    }

    public JSONObject json() {
        try {
            return new JSONObject().put("primary", primary).put("fallback", fallback)
                .put("deviceName", deviceName).put("deviceId", deviceId).put("scope", scope)
                .put("username", username).put("accountId", accountId).put("mode", mode).put("theme", theme)
                .put("uploadSeconds", uploadSeconds).put("batterySeconds", batterySeconds)
                .put("batteryEnabled", batteryEnabled).put("uploadOnChange", uploadOnChange)
                .put("uploadOnSuspend", uploadOnSuspend).put("uploadOnShutdown", uploadOnShutdown)
                .put("bootEnabled", bootEnabled).put("aliases", new JSONObject(aliases.toString()))
                .put("colors", new JSONObject(colors.toString())).put("features", new JSONArray(features));
        } catch (Exception e) { throw new IllegalStateException(e); }
    }

    public boolean configured() { return !primary.isEmpty() && !apiKey.isEmpty() && accountId > 0 && !scope.isEmpty(); }
    public String modeName() { return mode.equals("xiaomi") ? "小米优化" : "通用安卓"; }
    public String displayName(String pkg, String original) { return aliases.optString(pkg.toLowerCase(Locale.ROOT), original); }
    public List<String> endpoints() {
        List<String> list = new ArrayList<>(); list.add(primary);
        if (!fallback.isEmpty() && !fallback.equals(primary)) list.add(fallback);
        return list;
    }
    public JSONObject device() {
        try { return new JSONObject().put("id", deviceId).put("name", deviceName).put("platform", "android").put("agent_version", VERSION); }
        catch (Exception e) { throw new IllegalStateException(e); }
    }

    public void validate() {
        primary = normalizeUrl(primary); fallback = fallback.trim().isEmpty() ? "" : normalizeUrl(fallback);
        deviceName = deviceName.trim();
        if (deviceName.isEmpty() || deviceName.length() > 100) throw new IllegalArgumentException("设备名称须为 1–100 个字符");
        if (apiKey.length() < 32 || apiKey.length() > 256 || apiKey.matches(".*\\s.*")) throw new IllegalArgumentException("请填写完整的上传密钥");
        if (uploadSeconds < 10 || uploadSeconds > 300) throw new IllegalArgumentException("上传间隔须为 10–300 秒");
        if (batterySeconds < 30 || batterySeconds > 3600) throw new IllegalArgumentException("电池记录间隔须为 30–3600 秒");
        if (!mode.equals("standard") && !mode.equals("xiaomi")) throw new IllegalArgumentException("保活模式无效");
        if (!java.util.Arrays.asList("system", "light", "dark").contains(theme)) throw new IllegalArgumentException("主题无效");
        if (aliases.length() > 500 || colors.length() > 500) throw new IllegalArgumentException("应用设置最多支持 500 项");
        for (String key : keys(aliases)) if (key.trim().isEmpty() || key.length() > 200 || aliases.optString(key).trim().isEmpty() || aliases.optString(key).length() > 200)
            throw new IllegalArgumentException("应用包名和显示名称须为 1–200 个字符");
        for (String key : keys(colors)) if (key.trim().isEmpty() || key.length() > 200 || !Palette.IDS.contains(colors.optString(key)))
            throw new IllegalArgumentException("应用颜色须从预设中选择");
    }

    public static List<String> keys(JSONObject j) {
        List<String> keys = new ArrayList<>(); j.keys().forEachRemaining(keys::add); return keys;
    }

    public static String normalizeUrl(String value) {
        try {
            URI uri = new URI(value.trim()); String scheme = uri.getScheme();
            if (scheme == null || !java.util.Arrays.asList("http", "https").contains(scheme.toLowerCase(Locale.ROOT)) || uri.getHost() == null
                || uri.getUserInfo() != null || uri.getRawQuery() != null || uri.getRawFragment() != null
                || !(uri.getPath() == null || uri.getPath().isEmpty() || uri.getPath().equals("/"))
                || uri.getPort() == 0 || uri.getPort() > 65535 || uri.getPort() < -1) throw new Exception();
            String host = uri.getHost().toLowerCase(Locale.ROOT);
            int port = uri.getPort(); scheme = scheme.toLowerCase(Locale.ROOT);
            if ((scheme.equals("https") && port == 443) || (scheme.equals("http") && port == 80)) port = -1;
            return new URI(scheme, null, host, port, null, null, null).toASCIIString();
        } catch (Exception e) { throw new IllegalArgumentException("地址格式示例：https://example.com 或 http://192.168.1.10:8080，不要附带路径"); }
    }

    public static String sha256(String value) {
        try {
            byte[] digest = MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8));
            StringBuilder b = new StringBuilder(); for (byte v : digest) b.append(String.format(Locale.ROOT, "%02x", v & 255)); return b.toString();
        } catch (Exception e) { throw new IllegalStateException(e); }
    }
}
