package com.focusledger.android;

import android.media.MediaMetadata;
import android.media.session.MediaController;
import android.media.session.MediaSession;
import android.media.session.PlaybackState;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.RuntimeEnvironment;
import org.robolectric.annotation.Config;
import static org.junit.Assert.*;

@RunWith(RobolectricTestRunner.class)
@Config(sdk = {28, 36})
public class MusicReaderTest {
    private static MediaMetadata metadata(String title) { return new MediaMetadata.Builder().putString(MediaMetadata.METADATA_KEY_TITLE, title).putString(MediaMetadata.METADATA_KEY_ARTIST, "歌手").build(); }
    private static PlaybackState state(int value) { return new PlaybackState.Builder().setState(value, 0, 1).build(); }

    @Test public void metadataTracksPlayingPausedAndStopped() {
        JSONObject playing = MusicReader.track(metadata("测试歌曲"), state(PlaybackState.STATE_PLAYING), "music.app", "播放器");
        assertEquals("测试歌曲", playing.optString("title")); assertEquals("歌手", playing.optString("artist"));
        assertEquals("playing", playing.optString("state")); assertEquals("music.app", playing.optString("process_name"));
        assertEquals("paused", MusicReader.track(metadata("测试歌曲"), state(PlaybackState.STATE_PAUSED), "music.app", "播放器").optString("state"));
        assertNull(MusicReader.track(metadata("测试歌曲"), state(PlaybackState.STATE_STOPPED), "music.app", "播放器"));
        assertNull(MusicReader.track(metadata("  "), state(PlaybackState.STATE_PLAYING), "music.app", "播放器"));
        assertNull(MusicReader.track(null, state(PlaybackState.STATE_PLAYING), "music.app", "播放器"));
    }
    @Test public void missingPermissionAndDisabledCollectionClearSnapshot() {
        android.content.Context context = RuntimeEnvironment.getApplication();
        MusicReader reader = new MusicReader(context, new UsageReader(context));
        com.focusledger.android.Config config = new com.focusledger.android.Config();
        assertFalse(MusicReader.permitted(context));
        reader.refresh(config, true, true); assertTrue(reader.snapshot().isNull("track"));
        config.musicEnabled = false; reader.refresh(config, true, true); assertTrue(reader.snapshot().isNull("track"));
        reader.refresh(config, false, true); assertTrue(reader.snapshot().isNull("track"));
    }
    @Test public void playingSessionWinsOverPausedSession() {
        android.content.Context context = RuntimeEnvironment.getApplication();
        MediaSession paused = new MediaSession(context, "paused"), playing = new MediaSession(context, "playing");
        try {
            org.robolectric.Shadows.shadowOf(paused.getController()).setMetadata(metadata("暂停的歌"));
            org.robolectric.Shadows.shadowOf(paused.getController()).setPlaybackState(state(PlaybackState.STATE_PAUSED));
            org.robolectric.Shadows.shadowOf(playing.getController()).setMetadata(metadata("正在播放"));
            org.robolectric.Shadows.shadowOf(playing.getController()).setPlaybackState(state(PlaybackState.STATE_PLAYING));
            org.robolectric.Shadows.shadowOf(paused.getController()).setPackageName("test.paused");
            org.robolectric.Shadows.shadowOf(playing.getController()).setPackageName("test.playing");
            JSONObject selected = MusicReader.choose(java.util.Arrays.asList(paused.getController(), playing.getController()), new UsageReader(context));
            assertEquals("正在播放", selected.optString("title"));
        } finally { paused.release(); playing.release(); }
    }
    @Test public void musicSettingSurvivesCopyAndUpgrade() {
        com.focusledger.android.Config config = new com.focusledger.android.Config(new JSONObject());
        assertTrue(config.musicEnabled); config.musicEnabled = false;
        assertFalse(config.copy().musicEnabled);
    }
    @Test public void callbacksRefreshTracksAndAreReleasedWhenPaused() {
        android.content.Context context = RuntimeEnvironment.getApplication();
        org.robolectric.Shadows.shadowOf(context.getSystemService(android.app.NotificationManager.class))
            .setNotificationListenerAccessGranted(MusicReader.component(context), true);
        MediaSession session = new MediaSession(context, "callbacks");
        MediaController controller = session.getController();
        var shadow = org.robolectric.Shadows.shadowOf(controller);
        shadow.setMetadata(metadata("第一首")); shadow.setPlaybackState(state(PlaybackState.STATE_PLAYING));
        org.robolectric.Shadows.shadowOf(context.getSystemService(android.media.session.MediaSessionManager.class)).addController(controller);
        com.focusledger.android.Config config = new com.focusledger.android.Config();
        MusicReader[] ref = new MusicReader[1];
        ref[0] = new MusicReader(context, new UsageReader(context), () -> ref[0].refresh(config, true, true));
        MusicReader reader = ref[0];
        try {
            assertTrue(reader.refresh(config, true, true));
            assertEquals(1, shadow.getCallbacks().size());
            // No two-second polling; a player callback still updates immediately.
            assertTrue(reader.nextDelay(android.os.SystemClock.elapsedRealtime()) > 2000);
            shadow.setMetadata(metadata("第二首")); shadow.executeOnMetadataChanged(metadata("第二首"));
            org.robolectric.Shadows.shadowOf(android.os.Looper.getMainLooper()).idle();
            assertEquals("第二首", reader.snapshot().optJSONObject("track").optString("title"));
            shadow.setPlaybackState(state(PlaybackState.STATE_PAUSED)); shadow.executeOnPlaybackStateChanged(state(PlaybackState.STATE_PAUSED));
            org.robolectric.Shadows.shadowOf(android.os.Looper.getMainLooper()).idle();
            assertEquals("paused", reader.snapshot().optJSONObject("track").optString("state"));
            reader.refresh(config, true, true); assertEquals(1, shadow.getCallbacks().size());
            assertTrue(reader.refresh(config, false, true));
            assertTrue(reader.snapshot().isNull("track")); assertTrue(shadow.getCallbacks().isEmpty());
            reader.refresh(config, true, true); assertEquals(1, shadow.getCallbacks().size());
            org.robolectric.Shadows.shadowOf(context.getSystemService(android.app.NotificationManager.class))
                .setNotificationListenerAccessGranted(MusicReader.component(context), false);
            reader.refresh(config, true, true);
            assertTrue(reader.snapshot().isNull("track")); assertTrue(shadow.getCallbacks().isEmpty());
        } finally { reader.close(); session.release(); }
    }
    @Test public void periodicRefreshRecoversAMissedPlayerCallback() {
        android.content.Context context = RuntimeEnvironment.getApplication();
        org.robolectric.Shadows.shadowOf(context.getSystemService(android.app.NotificationManager.class))
            .setNotificationListenerAccessGranted(MusicReader.component(context), true);
        MediaSession session = new MediaSession(context, "fallback");
        var shadow = org.robolectric.Shadows.shadowOf(session.getController());
        shadow.setMetadata(metadata("原歌曲")); shadow.setPlaybackState(state(PlaybackState.STATE_PLAYING));
        org.robolectric.Shadows.shadowOf(context.getSystemService(android.media.session.MediaSessionManager.class)).addController(session.getController());
        MusicReader reader = new MusicReader(context, new UsageReader(context));
        com.focusledger.android.Config config = new com.focusledger.android.Config();
        try {
            reader.refresh(config, false, true);
            assertTrue("Starting collection must not wait for the idle read deadline", reader.refresh(config, true, false));
            shadow.setMetadata(metadata("漏回调的歌曲"));
            org.robolectric.shadows.ShadowSystemClock.advanceBy(java.time.Duration.ofSeconds(2));
            assertFalse(reader.refresh(config, true, false));
            assertEquals("原歌曲", reader.snapshot().optJSONObject("track").optString("title"));
            org.robolectric.shadows.ShadowSystemClock.advanceBy(java.time.Duration.ofSeconds(28));
            assertTrue(reader.refresh(config, true, false));
            assertEquals("漏回调的歌曲", reader.snapshot().optJSONObject("track").optString("title"));
        } finally { reader.close(); session.release(); }
    }
}
