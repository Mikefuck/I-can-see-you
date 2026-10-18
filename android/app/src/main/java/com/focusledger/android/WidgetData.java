package com.focusledger.android;

import org.json.JSONArray;
import org.json.JSONObject;
import java.time.Instant;
import java.time.ZoneId;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;

/** The same daily runs as the web timetable. All times here are epoch seconds. */
final class WidgetData {
    record Run(double start, double end, String color, String app) {}
    record Device(String owner, String id, String name, String state, String current, double lastSeen,
                  double seconds, List<Run> runs) {}
    final double now, start, end;
    final List<Device> devices;
    WidgetData(double now, double start, double end, List<Device> devices) {
        this.now = now; this.start = start; this.end = end; this.devices = devices;
    }
    static double dayStart(double seconds, ZoneId zone) {
        return Instant.ofEpochSecond((long)seconds).atZone(zone).toLocalDate().atStartOfDay(zone).toEpochSecond();
    }
    static WidgetData parse(JSONObject data, ZoneId zone) throws Exception {
        double now = data.getDouble("now"), base = data.getDouble("base");
        if (!Double.isFinite(now) || !Double.isFinite(base)) throw new IllegalArgumentException("看板时间无效");
        double start = dayStart(now, zone);
        double end = Instant.ofEpochSecond((long)start).atZone(zone).toLocalDate().plusDays(1).atStartOfDay(zone).toEpochSecond();
        JSONArray apps = data.getJSONArray("apps"), colors = data.optJSONArray("app_colors"), people = data.getJSONArray("people");
        List<Device> devices = new ArrayList<>();
        for (int p = 0; p < people.length(); p++) {
            JSONObject person = people.getJSONObject(p); JSONArray owned = person.getJSONArray("devices");
            for (int d = 0; d < owned.length(); d++) {
                JSONObject device = owned.getJSONObject(d); JSONArray source = device.optJSONArray("runs");
                List<Run> runs = new ArrayList<>();
                if (source != null) for (int r = 0; r < source.length(); r++) {
                    JSONArray row = source.getJSONArray(r); int app = row.optInt(2, -1);
                    double s = Math.max(start, base + row.getDouble(0)), e = Math.min(now, Math.min(end, base + row.getDouble(1)));
                    if (!Double.isFinite(s) || !Double.isFinite(e) || e <= s) continue;
                    JSONArray item = apps.optJSONArray(app);
                    runs.add(new Run(s, e, colors == null ? "slate" : colors.optString(app, "slate"), item == null ? "" : item.optString(0)));
                }
                runs.sort(Comparator.comparingDouble(Run::start));
                List<Run> joined = new ArrayList<>();
                for (Run run : runs) {
                    Run last = joined.isEmpty() ? null : joined.get(joined.size() - 1);
                    if (last != null && last.app.equals(run.app) && last.color.equals(run.color) && run.start <= last.end)
                        joined.set(joined.size() - 1, new Run(last.start, Math.max(last.end, run.end), last.color, last.app));
                    else joined.add(run);
                }
                runs = joined;
                // Union overlaps for this device; different devices are deliberately added, as on the web.
                double total = 0, until = start;
                for (Run run : runs) { total += Math.max(0, run.end - Math.max(until, run.start)); until = Math.max(until, run.end); }
                JSONObject last = device.optJSONObject("last");
                devices.add(new Device(person.getString("username"), device.getString("id"), device.getString("name"),
                    device.optString("state", "offline"), last == null ? "" : last.optString("app"), device.optDouble("last_seen"), total, runs));
            }
        }
        return new WidgetData(now, start, end, devices);
    }
    List<Device> filtered(String user, String device) {
        List<Device> result = new ArrayList<>();
        for (Device d : devices) if ((user.isEmpty() || d.owner.equals(user)) && (device.isEmpty() || d.id.equals(device))) result.add(d);
        return result;
    }
    static String duration(double seconds) {
        long minutes = (long)Math.max(0, seconds) / 60;
        if (seconds > 0 && minutes == 0) return "<1分";
        return minutes < 60 ? minutes + "分" : minutes / 60 + "时" + String.format(java.util.Locale.ROOT, "%02d", minutes % 60) + "分";
    }
    static String state(Device d, boolean stale) {
        if (stale) return "快照 · " + (d.current.isEmpty() ? "暂无应用" : d.current);
        return switch (d.state) {
            case "active" -> "使用中" + (d.current.isEmpty() ? "" : " · " + d.current);
            case "idle" -> "空闲";
            case "asleep" -> "休眠";
            case "off" -> "关机";
            default -> "离线";
        };
    }
    String date(ZoneId zone) { return DateTimeFormatter.ofPattern("M月d日").withZone(zone).format(Instant.ofEpochSecond((long)now)); }
}
