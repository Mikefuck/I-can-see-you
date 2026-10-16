package com.focusledger.android;

import android.service.notification.NotificationListenerService;

/** Android requires an enabled notification listener to access other apps' media sessions.
 * No notification contents are inspected, saved or uploaded. */
public final class MusicListener extends NotificationListenerService {
    @Override public void onListenerConnected() { super.onListenerConnected(); Agent.get(this).refreshMusic(); }
    @Override public void onListenerDisconnected() { Agent.get(this).refreshMusic(); super.onListenerDisconnected(); }
}
