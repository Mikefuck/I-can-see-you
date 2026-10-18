package com.focusledger.android;

import org.json.JSONObject;
import org.junit.Test;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.time.ZoneId;
import java.util.concurrent.atomic.AtomicInteger;
import static org.junit.Assert.*;

public class WidgetNetworkTest {
    private void json(TestHttpServer.Exchange e, int code, String data) throws Exception {
        byte[] bytes = data.getBytes(StandardCharsets.UTF_8); e.sendResponseHeaders(code, bytes.length); e.getResponseBody().write(bytes); e.close();
    }
    @Test public void memberAuthorizationUsesShortLoginAndOnlyReadTokenForFetching() throws Exception {
        TestHttpServer server = TestHttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0); AtomicInteger signedOut = new AtomicInteger();
        try {
            server.createContext("/api/v1/management/login", e -> {
                assertNull(e.getRequestHeaders().getFirst("Authorization")); assertEquals("desktop", e.getRequestHeaders().getFirst("X-FocusLedger-Client"));
                e.getResponseHeaders().add("Set-Cookie", "focus_session=temporary; HttpOnly; Path=/"); json(e, 200, "{\"csrf\":\"csrf\"}");
            });
            server.createContext("/api/v1/management/widget-token", e -> {
                assertEquals("focus_session=temporary", e.getRequestHeaders().getFirst("Cookie")); assertEquals("csrf", e.getRequestHeaders().getFirst("X-CSRF-Token"));
                json(e, 200, new JSONObject().put("scope", "widget:board:read").put("token", "widget-read-" + "x".repeat(40)).put("username", "alice").put("expires_at", 9999999999d).toString());
            });
            server.createContext("/api/v1/management/logout", e -> { signedOut.incrementAndGet(); json(e, 200, "{}"); });
            String path = "/api/v1/widget/board?since=" + (long)WidgetData.dayStart(System.currentTimeMillis() / 1000d, ZoneId.systemDefault());
            server.createContext(path, e -> {
                assertNull(e.getRequestHeaders().getFirst("Cookie")); assertEquals("Bearer widget-read-" + "x".repeat(40), e.getRequestHeaders().getFirst("Authorization"));
                json(e, 200, WidgetDataTest.sample().toString());
            });
            server.start(); WidgetStore.Options o = new WidgetStore.Options(); o.primary = "http://127.0.0.1:" + server.getAddress().getPort(); o.mode = "members";
            WidgetNetwork network = new WidgetNetwork(); network.authorize(o, "alice", "test-password");
            assertEquals(1, signedOut.get()); assertEquals("alice", o.account); assertEquals(3, WidgetData.parse(network.fetch(o), ZoneId.systemDefault()).devices.size());
        } finally { server.stop(0); }
    }
    @Test public void authorizationFailureDoesNotSilentlySwitchToPublicOrAnotherIdentity() throws Exception {
        TestHttpServer primary = TestHttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0), fallback = TestHttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        AtomicInteger attempted = new AtomicInteger();
        try {
            String path = "/api/v1/widget/board?since=" + (long)WidgetData.dayStart(System.currentTimeMillis() / 1000d, ZoneId.systemDefault());
            primary.createContext(path, e -> json(e, 401, "{}")); fallback.createContext(path, e -> { attempted.incrementAndGet(); json(e, 200, "{}"); }); primary.start(); fallback.start();
            WidgetStore.Options o = new WidgetStore.Options(); o.primary = "http://127.0.0.1:" + primary.getAddress().getPort(); o.fallback = "http://127.0.0.1:" + fallback.getAddress().getPort(); o.mode = "members"; o.token = "read-token";
            try { new WidgetNetwork().fetch(o); fail(); } catch (Transport.ApiError expected) { assertEquals(401, expected.status); }
            assertEquals(0, attempted.get());
        } finally { primary.stop(0); fallback.stop(0); }
    }
}
