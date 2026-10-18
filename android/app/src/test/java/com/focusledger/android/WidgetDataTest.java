package com.focusledger.android;

import org.json.JSONObject;
import org.junit.Test;
import java.time.Instant;
import java.time.ZoneId;
import static org.junit.Assert.*;

public class WidgetDataTest {
    static JSONObject sample() throws Exception {
        long start = (long)WidgetData.dayStart(System.currentTimeMillis() / 1000d, ZoneId.systemDefault());
        JSONObject data = new JSONObject("""
            {"apps":[["浏览器","browser"],["编辑器","code"]],"app_colors":["teal","slate"],"people":[
              {"username":"alice","devices":[{"id":"phone","name":"Redmi K90","state":"active","last":{"app":"浏览器"},"runs":[[28800,30600,0],[30600,32400,1],[32000,32400,1]]},
                {"id":"pc","name":"工作电脑","state":"idle","runs":[[36000,39600,1]]}]},
              {"username":"bob","devices":[{"id":"tablet","name":"平板","state":"offline","runs":[[-60,60,0],[86300,90000,0]]}]}]}
            """);
        return data.put("now", Math.max(start + 16 * 3600, System.currentTimeMillis() / 1000d)).put("base", start);
    }
    @Test public void clipsMidnightAndUnionsOverlapsWithinOneDevice() throws Exception {
        WidgetData data = WidgetData.parse(sample(), ZoneId.systemDefault());
        assertEquals(3600, data.devices.get(0).seconds(), 0); assertEquals(3600, data.devices.get(1).seconds(), 0);
        assertEquals(2, data.devices.get(0).runs().size());
        assertEquals(60, data.devices.get(2).seconds(), 0); assertEquals(1, data.devices.get(2).runs().size());
        assertEquals("teal", data.devices.get(0).runs().get(0).color());
        assertEquals(2, data.filtered("alice", "").size()); assertEquals(1, data.filtered("alice", "pc").size());
        assertTrue(data.filtered("bob", "pc").isEmpty());
    }
    @Test public void calendarDayIncludesDaylightSavingTimeAndViewerZone() {
        ZoneId zone = ZoneId.of("America/New_York");
        double morning = Instant.parse("2026-03-08T12:00:00Z").getEpochSecond();
        assertEquals(Instant.parse("2026-03-08T05:00:00Z").getEpochSecond(), WidgetData.dayStart(morning, zone), 0);
        double next = Instant.parse("2026-03-09T12:00:00Z").getEpochSecond();
        assertEquals(23 * 3600, WidgetData.dayStart(next, zone) - WidgetData.dayStart(morning, zone), 0);
    }
    @Test public void staleDataDoesNotClaimDeviceIsLive() throws Exception {
        WidgetData.Device device = WidgetData.parse(sample(), ZoneId.systemDefault()).devices.get(0);
        assertEquals("使用中 · 浏览器", WidgetData.state(device, false)); assertEquals("快照 · 浏览器", WidgetData.state(device, true));
        assertEquals("<1分", WidgetData.duration(30)); assertEquals("1时05分", WidgetData.duration(3900));
    }
}
