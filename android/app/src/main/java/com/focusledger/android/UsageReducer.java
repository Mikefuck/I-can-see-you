package com.focusledger.android;

import org.json.JSONObject;
import java.util.Objects;

/** Pure event reducer. Its state and the slices it emits must be committed in one transaction. */
public final class UsageReducer {
    public static final int RESUMED = 1, PAUSED = 2, SCREEN_ON = 15, SCREEN_OFF = 16;
    public static final int LOCKED = 17, UNLOCKED = 18, SHUTDOWN = 26, STARTUP = 27;
    public static final long SEGMENT_MS = 30_000;
    public interface Sink { void usage(String pkg, long start, long end); }
    public long cursor, segmentStart, activeSince;
    public boolean interactive, unlocked;
    public String candidate;
    private final Sink sink;

    public UsageReducer(long at, boolean interactive, boolean unlocked, Sink sink) {
        cursor = segmentStart = activeSince = at; this.interactive = interactive; this.unlocked = unlocked; this.sink = sink;
    }
    public UsageReducer(JSONObject state, Sink sink) {
        cursor = state.optLong("cursor"); segmentStart = state.optLong("segmentStart", cursor);
        activeSince = state.optLong("activeSince", cursor); interactive = state.optBoolean("interactive");
        unlocked = state.optBoolean("unlocked"); candidate = state.isNull("candidate") ? null : state.optString("candidate", null);
        this.sink = sink;
    }
    public String active() { return interactive && unlocked ? candidate : null; }
    public void advance(long at) {
        if (at < cursor) throw new IllegalArgumentException("时间倒退");
        if (active() != null) while (at - segmentStart >= SEGMENT_MS) {
            sink.usage(active(), segmentStart, segmentStart + SEGMENT_MS); segmentStart += SEGMENT_MS;
        }
        cursor = at;
    }
    private void flush(long at) {
        if (active() != null && at > segmentStart) sink.usage(active(), segmentStart, at);
        segmentStart = at;
    }
    public void event(int type, String pkg, long at) {
        if (at < cursor) return;
        advance(at); String before = active();
        String nextCandidate = candidate; boolean nextInteractive = interactive, nextUnlocked = unlocked;
        switch (type) {
            case RESUMED: if (pkg != null && !pkg.isEmpty()) nextCandidate = pkg; break;
            case PAUSED: if (Objects.equals(candidate, pkg)) nextCandidate = null; break;
            case SCREEN_ON: nextInteractive = true; break;
            case SCREEN_OFF: nextInteractive = false; nextUnlocked = false; break;
            case LOCKED: nextUnlocked = false; break;
            case UNLOCKED: nextInteractive = true; nextUnlocked = true; break;
            case SHUTDOWN: case STARTUP: nextCandidate = null; nextInteractive = false; nextUnlocked = false; break;
            default: return;
        }
        String after = nextInteractive && nextUnlocked ? nextCandidate : null;
        if (!Objects.equals(before, after)) { flush(at); activeSince = at; segmentStart = at; }
        candidate = nextCandidate; interactive = nextInteractive; unlocked = nextUnlocked;
    }
    public void reconcile(boolean screen, boolean unlockedNow, long at) {
        if (!screen) event(SCREEN_OFF, null, at);
        else if (!unlockedNow) { event(SCREEN_ON, null, at); event(LOCKED, null, at); }
        else { event(SCREEN_ON, null, at); event(UNLOCKED, null, at); }
    }
    public void stop(long at) { advance(at); flush(at); candidate = null; activeSince = at; }
    public void startHere(long at, boolean screen, boolean unlockedNow) {
        cursor = segmentStart = activeSince = at; interactive = screen; unlocked = unlockedNow;
    }
    public JSONObject json() {
        try { return new JSONObject().put("cursor", cursor).put("segmentStart", segmentStart).put("activeSince", activeSince)
            .put("interactive", interactive).put("unlocked", unlocked).put("candidate", candidate == null ? JSONObject.NULL : candidate); }
        catch (Exception e) { throw new IllegalStateException(e); }
    }
}
