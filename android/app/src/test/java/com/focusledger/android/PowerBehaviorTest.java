package com.focusledger.android;

import android.app.AppOpsManager;
import android.app.KeyguardManager;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.content.Context;
import android.os.PowerManager;
import android.os.SystemClock;
import org.junit.After;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.Robolectric;
import org.robolectric.RuntimeEnvironment;
import org.robolectric.Shadows;
import org.robolectric.util.ReflectionHelpers;
import java.util.concurrent.TimeUnit;
import static org.junit.Assert.*;

@RunWith(org.robolectric.RobolectricTestRunner.class)
@org.robolectric.annotation.Config(sdk = {28, 36})
public class PowerBehaviorTest {
    private Agent agent;
    private Context context;
    @Before public void setup() {
        ReflectionHelpers.setStaticField(Agent.class, "instance", null);
        context = RuntimeEnvironment.getApplication(); agent = Agent.get(context);
        Config config = new Config(); config.primary = "https://example.invalid"; config.apiKey = "test";
        config.accountId = 1; config.scope = "power-tests"; config.musicEnabled = false;
        ReflectionHelpers.setField(agent.settings, "config", config);
        agent.settings.intent(true, true);
        long now = SystemClock.elapsedRealtime();
        ReflectionHelpers.setField(agent, "nextCapture", now + 60_000);
        ReflectionHelpers.setField(agent, "nextBattery", now + 300_000);
        ReflectionHelpers.setField(agent, "nextCleanup", now + 3600_000);
        ReflectionHelpers.setField(agent.uploader, "regularAfter", now + 30_000);
        agent.music.refresh(config, true, true);
    }
    @After public void cleanup() throws Exception {
        agent.service = null;
        agent.collector.shutdownNow(); agent.collector.awaitTermination(10, TimeUnit.SECONDS);
        java.util.concurrent.ExecutorService uploads = ReflectionHelpers.getField(agent.uploader, "executor");
        uploads.shutdownNow(); uploads.awaitTermination(10, TimeUnit.SECONDS);
        agent.io.shutdownNow(); agent.music.close(); agent.store.close();
        ReflectionHelpers.setStaticField(Agent.class, "instance", null);
    }
    @Test public void screenOffAndPauseDoNotPollEverySecondButUnlockDoes() {
        Shadows.shadowOf(context.getSystemService(PowerManager.class)).setIsInteractive(false);
        assertEquals(30_000, agent.nextTickDelay());
        Shadows.shadowOf(context.getSystemService(PowerManager.class)).setIsInteractive(true);
        Shadows.shadowOf(context.getSystemService(KeyguardManager.class)).setKeyguardLocked(true);
        assertEquals(30_000, agent.nextTickDelay());
        Shadows.shadowOf(context.getSystemService(KeyguardManager.class)).setKeyguardLocked(false);
        assertEquals(1000, agent.nextTickDelay());
        agent.settings.intent(true, false);
        assertEquals(30_000, agent.nextTickDelay());
    }
    @Test public void earlierBatteryAndUploadDeadlinesArePreserved() {
        Shadows.shadowOf(context.getSystemService(PowerManager.class)).setIsInteractive(false);
        ReflectionHelpers.setField(agent, "nextBattery", SystemClock.elapsedRealtime() + 5000);
        assertEquals(5000, agent.nextTickDelay());
        ReflectionHelpers.setField(agent.uploader, "regularAfter", SystemClock.elapsedRealtime() + 3000);
        assertEquals(3000, agent.nextTickDelay());
    }
    @Test public void activeServiceDoesNotRunDuplicateRecoveryUpload() throws Exception {
        agent.service = new CollectorService();
        java.util.concurrent.CountDownLatch done = new java.util.concurrent.CountDownLatch(1);
        agent.recover(done::countDown); assertTrue(done.await(5, TimeUnit.SECONDS));
        assertNull(agent.store.checkpoint("power-tests"));
        assertFalse(agent.uploader.busy());
        assertEquals("", agent.store.get("power-tests:last_error", ""));
    }
    @Test public void startWithoutNotificationsDoesNotRequestPermission() throws Exception {
        agent.settings.intent(false, false);
        Shadows.shadowOf(context.getSystemService(AppOpsManager.class)).setMode(AppOpsManager.OPSTR_GET_USAGE_STATS,
            android.os.Process.myUid(), context.getPackageName(), AppOpsManager.MODE_ALLOWED);
        Shadows.shadowOf(context.getSystemService(NotificationManager.class)).setNotificationsEnabled(false);
        try (var controller = Robolectric.buildActivity(MainActivity.class).setup()) {
            controller.get().control(); agent.collector.submit(() -> {}).get(5, TimeUnit.SECONDS);
            assertNull(Shadows.shadowOf(controller.get()).getLastRequestedPermission());
            assertTrue(agent.settings.wanted()); assertTrue(agent.settings.tracking());
            assertNotNull(Shadows.shadowOf(RuntimeEnvironment.getApplication()).getNextStartedService());
        }
    }
    @Test public void disabledChannelIsReportedAndSettingsTargetsIt() {
        NotificationManager manager = context.getSystemService(NotificationManager.class);
        manager.createNotificationChannel(new NotificationChannel(CollectorService.CHANNEL, "状态", NotificationManager.IMPORTANCE_NONE));
        assertFalse(KeepAlive.notifications(context));
        try (var controller = Robolectric.buildActivity(MainActivity.class).setup()) {
            KeepAlive.notificationSettings(controller.get());
            android.content.Intent intent = Shadows.shadowOf(controller.get()).getNextStartedActivity();
            assertEquals(android.provider.Settings.ACTION_CHANNEL_NOTIFICATION_SETTINGS, intent.getAction());
            assertEquals(CollectorService.CHANNEL, intent.getStringExtra(android.provider.Settings.EXTRA_CHANNEL_ID));
        }
    }
}
