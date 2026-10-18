package com.focusledger.android;

import org.json.JSONArray;
import org.json.JSONObject;
import org.junit.After;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RuntimeEnvironment;
import org.robolectric.util.ReflectionHelpers;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;
import static org.junit.Assert.*;

@RunWith(org.robolectric.RobolectricTestRunner.class)
@org.robolectric.annotation.Config(sdk = {28, 36})
public class UploaderTest {
    private Agent agent;
    private TestHttpServer server;
    private Config config;
    private final AtomicReference<JSONObject> uploaded = new AtomicReference<>();
    private final AtomicInteger checks = new AtomicInteger();
    private volatile boolean supportsMusic = true;
    private volatile int checkStatus = 200;
    private volatile long accountId = 1;

    @Before public void setup() throws Exception {
        ReflectionHelpers.setStaticField(Agent.class, "instance", null);
        agent = Agent.get(RuntimeEnvironment.getApplication());
        server = TestHttpServer.create(new java.net.InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/api/v1/agent/check", exchange -> {
            checks.incrementAndGet();
            reply(exchange, checkStatus, new JSONObject().put("ok", true).put("schema_version", 1)
                .put("account_id", accountId).put("username", "test")
                .put("features", new JSONArray(supportsMusic ? List.of("foreground", "music") : List.of("foreground"))));
        });
        server.createContext("/api/v1/usage/batches", exchange -> {
            uploaded.set(new JSONObject(new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8)));
            reply(exchange, 200, new JSONObject().put("acknowledged_ids", new JSONArray()));
        });
        server.start();
        config = new Config(); config.primary = "http://127.0.0.1:" + server.getAddress().getPort();
        config.apiKey = "test-upload-key-123456789012345678901";
        config.accountId = 1; config.username = "test"; config.scope = "test";
        // Existing installation verified against a server before music was supported.
        config.features.add("foreground");
        ReflectionHelpers.setField(agent.settings, "config", config);
        track("playing");
    }

    @After public void teardown() throws Exception {
        java.util.concurrent.ExecutorService executor = ReflectionHelpers.getField(agent.uploader, "executor");
        executor.shutdownNow(); executor.awaitTermination(10, TimeUnit.SECONDS);
        agent.collector.shutdownNow(); agent.io.shutdownNow(); agent.store.close();
        ReflectionHelpers.setStaticField(Agent.class, "instance", null);
        server.stop(0);
    }

    private static void reply(TestHttpServer.Exchange exchange, int status, JSONObject body) throws Exception {
        byte[] bytes = body.toString().getBytes(StandardCharsets.UTF_8);
        exchange.sendResponseHeaders(status, bytes.length); exchange.getResponseBody().write(bytes); exchange.close();
    }
    private void track(String state) throws Exception {
        JSONObject track = new JSONObject().put("title", "安卓测试歌曲").put("artist", "测试歌手")
            .put("album", "").put("app_name", "播放器").put("process_name", "test.music").put("state", state);
        ReflectionHelpers.setField(agent.music, "snapshot", new JSONObject().put("observed_at", LedgerStore.iso(System.currentTimeMillis()))
            .put("track", state == null ? JSONObject.NULL : track).toString());
    }
    private void upload(boolean manual) throws Exception {
        CountDownLatch idle = new CountDownLatch(1);
        agent.uploader.request(manual, true); agent.uploader.whenIdle(idle::countDown);
        assertTrue("Upload did not finish", idle.await(10, TimeUnit.SECONDS));
    }

    @Test public void upgradedServerUploadsMusic() throws Exception {
        upload(false);
        assertNotNull("Missing upload", uploaded.get());
        assertTrue("Locally recognized music was omitted from a successful upload", uploaded.get().has("music"));
        assertEquals("安卓测试歌曲", uploaded.get().getJSONObject("music").getJSONObject("track").getString("title"));
        assertEquals("", agent.store.get(config.scope + ":last_error", ""));
        assertEquals(1, checks.get());
        track("paused"); upload(false);
        assertEquals("paused", uploaded.get().getJSONObject("music").getJSONObject("track").getString("state"));
        track(null); upload(false);
        assertTrue(uploaded.get().getJSONObject("music").isNull("track"));
        assertEquals("Regular uploads should reuse recently checked capabilities", 1, checks.get());
    }

    @Test public void manualUploadRechecksServer() throws Exception {
        supportsMusic = false; upload(false);
        assertFalse(uploaded.get().has("music"));
        assertTrue(agent.store.get(config.scope + ":music_note", "").contains("不支持音乐同步"));
        assertFalse(agent.store.get(config.scope + ":last_upload", "").isEmpty());
        supportsMusic = true; upload(true);
        assertEquals(2, checks.get()); assertTrue(uploaded.get().has("music"));
        assertEquals("", agent.store.get(config.scope + ":music_note", "missing"));
    }

    @Test public void backgroundRechecksServer() throws Exception {
        supportsMusic = false; upload(false);
        supportsMusic = true;
        org.robolectric.shadows.ShadowSystemClock.advanceBy(java.time.Duration.ofMinutes(6));
        upload(false);
        assertEquals(2, checks.get()); assertTrue(uploaded.get().has("music"));
    }

    @Test public void idleWaitsForNextUpload() throws Exception {
        CountDownLatch uploadStarted = new CountDownLatch(1);
        CountDownLatch releaseUpload = new CountDownLatch(1);
        CountDownLatch idle = new CountDownLatch(1);
        server.createContext("/api/v1/usage/batches", exchange -> {
            uploadStarted.countDown();
            if (!releaseUpload.await(10, TimeUnit.SECONDS)) throw new IllegalStateException("Upload was not released");
            reply(exchange, 200, new JSONObject().put("acknowledged_ids", new JSONArray()));
        });
        try {
            agent.uploader.whenIdle(() -> {
                agent.uploader.request(false, true);
                agent.uploader.whenIdle(idle::countDown);
            });
            assertTrue("Upload did not start", uploadStarted.await(10, TimeUnit.SECONDS));
            assertEquals("Idle callback ran while the next upload was still active", 1L, idle.getCount());
        } finally {
            releaseUpload.countDown();
        }
        assertTrue("Idle callback did not run after upload finished", idle.await(10, TimeUnit.SECONDS));
    }

    @Test public void changedKeyRechecksServer() throws Exception {
        supportsMusic = false; upload(false);
        supportsMusic = true; config.apiKey = "another-test-upload-key-123456789012345678901";
        upload(false);
        assertEquals(2, checks.get()); assertTrue(uploaded.get().has("music"));
    }

    @Test public void checkFailureCanBeRetried() throws Exception {
        checkStatus = 503; upload(false);
        assertNull(uploaded.get());
        assertFalse(agent.store.get(config.scope + ":last_error", "").isEmpty());
        checkStatus = 200; upload(true);
        assertTrue(uploaded.get().has("music"));
        assertEquals("", agent.store.get(config.scope + ":last_error", "missing"));
    }

    @Test public void wrongAccountBlocksUpload() throws Exception {
        accountId = 2; upload(false);
        assertNull(uploaded.get());
        assertTrue(agent.store.get(config.scope + ":last_error", "").contains("账户已变化"));
        assertEquals("", agent.store.get(config.scope + ":last_upload", ""));
    }

    @Test public void disabledMusicHidesWarning() throws Exception {
        supportsMusic = false; config.musicEnabled = false; track(null); upload(false);
        assertFalse(uploaded.get().has("music"));
        assertEquals("", agent.store.get(config.scope + ":music_note", "missing"));
    }

    @Test public void unchangedConnectionIsChecked() throws Exception {
        // A failed explicit check must not silently take the offline settings-save path.
        checkStatus = 503;
        try (org.robolectric.android.controller.ActivityController<MainActivity> controller =
                 org.robolectric.Robolectric.buildActivity(MainActivity.class).setup()) {
            controller.get().verifyAndSave(config.copy(), () -> fail("Failed connection was saved"), true);
            agent.io.submit(() -> {}).get(10, TimeUnit.SECONDS);
            org.robolectric.Shadows.shadowOf(android.os.Looper.getMainLooper()).idle();
            assertEquals(1, checks.get());
        }
    }
}
