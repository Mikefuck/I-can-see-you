package com.focusledger.android;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

public final class BootReceiver extends BroadcastReceiver {
    @Override public void onReceive(Context context, Intent intent) {
        String action = intent.getAction();
        if (!Intent.ACTION_BOOT_COMPLETED.equals(action) && !Intent.ACTION_MY_PACKAGE_REPLACED.equals(action)) return;
        UsageWidgetProvider.renderAll(context); WidgetRefreshJob.schedule(context); WidgetRefreshJob.request(context);
        Agent agent = Agent.get(context); Config c = agent.settings.get();
        if (!agent.settings.wanted() || !c.configured()) return;
        if (Intent.ACTION_BOOT_COMPLETED.equals(action) && !c.bootEnabled) {
            agent.settings.intent(false, false); KeepAlive.schedule(context, false); return;
        }
        KeepAlive.schedule(context, true); KeepAlive.start(context, CollectorService.ACTION_RECOVER);
    }
}
