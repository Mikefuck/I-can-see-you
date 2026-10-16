package com.focusledger.android;

import org.json.JSONArray;
import org.json.JSONObject;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;
import java.util.UUID;

/** Real HTTP probe launched against an isolated repository server by tools/verify_server.py. */
public final class ServerIntegrationProbe {
    private static void check(boolean value, String message) { if (!value) throw new AssertionError(message); }
    public static void main(String[] args) throws Exception {
        JSONObject fixture = new JSONObject(new String(Files.readAllBytes(Path.of(args[0])), java.nio.charset.StandardCharsets.UTF_8));
        Config c = new Config(); c.primary = fixture.getString("url"); c.apiKey = fixture.getString("key");
        c.deviceName = "Android Integration"; c.scope = "integration";
        Transport transport = new Transport("b".repeat(64));
        JSONObject account = transport.check(c); check(account.getLong("account_id") == 1, "Account binding");
        long end = System.currentTimeMillis()-1000, start = end-30000;
        JSONObject usage = new JSONObject().put("id",UUID.randomUUID().toString()).put("kind","app_usage").put("app_name","Reader").put("process_name","org.example.reader")
            .put("started_at",java.time.Instant.ofEpochMilli(start).toString()).put("ended_at",java.time.Instant.ofEpochMilli(end).toString()).put("duration_seconds",30);
        JSONObject battery = new JSONObject().put("id",UUID.randomUUID().toString()).put("kind","device_status").put("occurred_at",java.time.Instant.ofEpochMilli(end).toString())
            .put("reason","periodic").put("battery_percent",82).put("charging",false).put("ac_online",false).put("battery_life_seconds",JSONObject.NULL);
        JSONObject foreground = new JSONObject().put("observed_at",java.time.Instant.now().toString()).put("since",java.time.Instant.ofEpochMilli(end).toString())
            .put("app",new JSONObject().put("app_name","Reader").put("process_name","org.example.reader"));
        JSONObject body = new JSONObject().put("schema_version",1).put("device",c.device()).put("events",new JSONArray().put(usage).put(battery)).put("foreground",foreground);
        JSONObject response = transport.request(c,"POST","/api/v1/usage/batches",body).json(); check(response.getJSONArray("acknowledged_ids").length()==2,"Upload ack");
        check(transport.request(c,"POST","/api/v1/usage/batches",body).json().getInt("duplicates")==2,"Retry idempotence");
        transport.request(c,"PUT","/api/v1/agent/app-aliases",new JSONObject().put("device",c.device()).put("app_aliases",new JSONObject().put("org.example.reader","阅读器")));
        transport.request(c,"PUT","/api/v1/agent/app-colors",new JSONObject().put("device",c.device()).put("app_colors",new JSONObject().put("org.example.reader","teal")));
        JSONObject device=transport.request(c,"GET","/api/web/live",null).json().getJSONArray("people").getJSONObject(0).getJSONArray("devices").getJSONObject(0);
        check("阅读器".equals(device.getJSONObject("last").getString("app")),"Live alias"); check("teal".equals(device.getJSONObject("last").getString("color")),"Live color");
        JSONObject music = new JSONObject().put("observed_at",java.time.Instant.now().toString()).put("track",new JSONObject()
            .put("title","安卓测试歌曲").put("artist","测试歌手").put("album", "").put("app_name","测试播放器").put("process_name","test.music").put("state","playing"));
        JSONObject musicBody = new JSONObject().put("schema_version",1).put("device",c.device()).put("events",new JSONArray()).put("music",music);
        transport.request(c,"POST","/api/v1/usage/batches",musicBody);
        device=transport.request(c,"GET","/api/web/live",null).json().getJSONArray("people").getJSONObject(0).getJSONArray("devices").getJSONObject(0);
        check("安卓测试歌曲".equals(device.getJSONObject("music").getString("title")),"Music metadata upload");
        music.put("observed_at",java.time.Instant.now().toString()).getJSONObject("track").put("state","paused");
        transport.request(c,"POST","/api/v1/usage/batches",musicBody);
        device=transport.request(c,"GET","/api/web/live",null).json().getJSONArray("people").getJSONObject(0).getJSONArray("devices").getJSONObject(0);
        check("paused".equals(device.getJSONObject("music").getString("state")),"Music pause upload");
        music.put("observed_at",java.time.Instant.now().toString()).put("track",JSONObject.NULL);
        transport.request(c,"POST","/api/v1/usage/batches",musicBody);
        device=transport.request(c,"GET","/api/web/live",null).json().getJSONArray("people").getJSONObject(0).getJSONArray("devices").getJSONObject(0);
        check(device.isNull("music"),"Music clear upload");
        Transport.Reply login=transport.at(c.primary,"POST","/api/v1/management/login",new JSONObject().put("username","android_admin").put("password",fixture.getString("password")),null,null,null,false,8000);
        String cookie="";
        for(Map.Entry<String,List<String>> header:login.headers().entrySet())if(header.getKey()!=null&&header.getKey().equalsIgnoreCase("Set-Cookie"))cookie=header.getValue().get(0).split(";",2)[0];
        check(!cookie.isEmpty(),"Management cookie"); String csrf=login.json().getString("csrf");
        transport.at(c.primary,"POST","/api/v1/management/users",new JSONObject().put("username","android_member").put("password",fixture.getString("password")).put("is_admin",false),null,cookie,csrf,false,8000);
        JSONArray users=transport.at(c.primary,"GET","/api/v1/management/users",null,null,cookie,csrf,false,8000).json().getJSONArray("users");check(users.length()==2,"User management");
        transport.at(c.primary,"PUT","/api/v1/management/settings",new JSONObject().put("retention_days",365),null,cookie,csrf,false,8000);
        JSONObject newKey=transport.at(c.primary,"POST","/api/v1/management/token",new JSONObject(),null,cookie,csrf,false,8000).json();
        try{transport.check(c);throw new AssertionError("Old key remained valid");}catch(Transport.ApiError e){check(e.status==401,"Old key invalidated");}
        c.apiKey=newKey.getString("api_key");check(transport.check(c).getLong("account_id")==1,"Rotated key binding");
        transport.request(c,"POST","/api/v1/usage/batches",body);
        transport.at(c.primary,"POST","/api/v1/management/logout",new JSONObject(),null,cookie,csrf,false,8000);
        System.out.println("Android real-server HTTP integration passed: usage, status, retries, gzip, live state, music playing/pause/clear, aliases, colors, management and key rotation.");
    }
}
