package com.focusledger.android;

import android.app.NotificationManager;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.media.MediaMetadata;
import android.media.session.MediaController;
import android.media.session.MediaSession;
import android.media.session.MediaSessionManager;
import android.media.session.PlaybackState;
import android.os.SystemClock;
import android.os.Handler;
import android.os.Looper;
import org.json.JSONObject;
import java.util.List;
import java.util.HashMap;
import java.util.Map;

/** Only reads published media-session metadata; never reads notification bodies or audio. */
final class MusicReader {
    private final Context context;
    private final UsageReader apps;
    private volatile String snapshot = "";
    private String previous = "";
    private long nextRead;
    private boolean previouslyEnabled;
    private final Runnable onChanged;
    private final Handler callbacks = new Handler(Looper.getMainLooper());
    private final Map<MediaSession.Token, MediaController> controllers = new HashMap<>();
    private final MediaSessionManager.OnActiveSessionsChangedListener sessionsChanged;
    private final MediaController.Callback controllerChanged;
    private boolean listening;
    MusicReader(Context context, UsageReader apps) { this(context, apps, () -> {}); }
    MusicReader(Context context, UsageReader apps, Runnable onChanged) {
        this.context = context; this.apps = apps; this.onChanged = onChanged;
        sessionsChanged = sessions -> this.onChanged.run();
        controllerChanged = new MediaController.Callback() {
            @Override public void onMetadataChanged(MediaMetadata metadata) { MusicReader.this.onChanged.run(); }
            @Override public void onPlaybackStateChanged(PlaybackState state) { MusicReader.this.onChanged.run(); }
            @Override public void onSessionDestroyed() { MusicReader.this.onChanged.run(); }
        };
    }
    long nextDelay(long now) { return nextRead - now; }
    void invalidate() { nextRead = 0; }
    static ComponentName component(Context context) { return new ComponentName(context, MusicListener.class); }
    static boolean permitted(Context context) {
        return context.getSystemService(NotificationManager.class).isNotificationListenerAccessGranted(component(context));
    }
    static void openSettings(MainActivity activity) {
        Intent intent = new Intent(android.provider.Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS);
        activity.startActivity(intent);
    }
    boolean refresh(Config config, boolean collecting, boolean force) {
        long elapsed = SystemClock.elapsedRealtime();
        boolean enabled = collecting && config.musicEnabled;
        if (!force && enabled == previouslyEnabled && elapsed < nextRead) return false;
        previouslyEnabled = enabled;
        nextRead = elapsed + 30_000;
        JSONObject track = null;
        if (enabled && permitted(context)) {
            try {
                MediaSessionManager manager = context.getSystemService(MediaSessionManager.class);
                List<MediaController> sessions = manager.getActiveSessions(component(context));
                track = choose(sessions, apps);
                try { observe(manager, sessions); }
                catch (RuntimeException ignored) { close(); nextRead = elapsed + 2000; }
            } catch (SecurityException | IllegalStateException ignored) { close(); /* Revocation clears the old track. */ }
        } else close();
        String value = track == null ? "" : track.toString();
        boolean changed = !value.equals(previous); previous = value;
        try { snapshot = new JSONObject().put("observed_at", LedgerStore.iso(System.currentTimeMillis()))
            .put("track", track == null ? JSONObject.NULL : track).toString(); }
        catch (Exception e) { throw new IllegalStateException(e); }
        return changed;
    }
    // Called only on the collector thread. Android callbacks enqueue a refresh there.
    private void observe(MediaSessionManager manager, List<MediaController> sessions) {
        if (!listening) {
            manager.addOnActiveSessionsChangedListener(sessionsChanged, component(context), callbacks);
            listening = true;
        }
        java.util.Set<MediaSession.Token> active = new java.util.HashSet<>();
        if (sessions != null) for (MediaController controller : sessions) {
            MediaSession.Token token = controller.getSessionToken(); active.add(token);
            if (!controllers.containsKey(token)) {
                controller.registerCallback(controllerChanged, callbacks); controllers.put(token, controller);
            }
        }
        java.util.Iterator<Map.Entry<MediaSession.Token, MediaController>> iterator = controllers.entrySet().iterator();
        while (iterator.hasNext()) {
            Map.Entry<MediaSession.Token, MediaController> entry = iterator.next();
            if (!active.contains(entry.getKey())) { entry.getValue().unregisterCallback(controllerChanged); iterator.remove(); }
        }
    }
    void close() {
        for (MediaController controller : controllers.values()) {
            try { controller.unregisterCallback(controllerChanged); } catch (RuntimeException ignored) {}
        }
        controllers.clear();
        if (listening) {
            try { context.getSystemService(MediaSessionManager.class).removeOnActiveSessionsChangedListener(sessionsChanged); }
            catch (RuntimeException ignored) {}
            listening = false;
        }
    }
    JSONObject snapshot() {
        try { return snapshot.isEmpty() ? new JSONObject().put("observed_at", LedgerStore.iso(System.currentTimeMillis())).put("track", JSONObject.NULL) : new JSONObject(snapshot); }
        catch (Exception e) { throw new IllegalStateException(e); }
    }
    static JSONObject choose(List<MediaController> sessions, UsageReader apps) {
        if (sessions == null) return null;
        JSONObject paused = null;
        for (MediaController controller : sessions) {
            try {
                JSONObject track = track(controller.getMetadata(), controller.getPlaybackState(), controller.getPackageName(), apps.label(controller.getPackageName()));
                if (track != null && "playing".equals(track.optString("state"))) return track;
                if (track != null && paused == null) paused = track;
            } catch (RuntimeException ignored) { /* A player may disappear between calls. */ }
        }
        return paused;
    }
    static JSONObject track(MediaMetadata metadata, PlaybackState state, String pkg, String label) {
        if (metadata == null || state == null || (state.getState() != PlaybackState.STATE_PLAYING && state.getState() != PlaybackState.STATE_PAUSED)) return null;
        String title = clean(metadata.getString(MediaMetadata.METADATA_KEY_TITLE), 300);
        if (title.isEmpty()) title = clean(metadata.getString(MediaMetadata.METADATA_KEY_DISPLAY_TITLE), 300);
        if (title.isEmpty()) return null;
        try {
            return new JSONObject().put("title", title).put("artist", clean(metadata.getString(MediaMetadata.METADATA_KEY_ARTIST), 300))
                .put("album", clean(metadata.getString(MediaMetadata.METADATA_KEY_ALBUM), 300))
                .put("app_name", clean(label == null || label.isEmpty() ? pkg : label, 200)).put("process_name", clean(pkg, 200))
                .put("state", state.getState() == PlaybackState.STATE_PLAYING ? "playing" : "paused");
        } catch (Exception e) { throw new IllegalStateException(e); }
    }
    private static String clean(String value, int max) { value = value == null ? "" : value.trim(); return value.length() > max ? value.substring(0, max) : value; }
}
