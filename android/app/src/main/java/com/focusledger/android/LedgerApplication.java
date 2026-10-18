package com.focusledger.android;

public final class LedgerApplication extends android.app.Application {
    @Override public void onCreate() {
        super.onCreate();
        // Components initialize the collector only when they use it. Widget jobs need no usage database.
    }
    @Override public void onConfigurationChanged(android.content.res.Configuration configuration) {
        super.onConfigurationChanged(configuration);
        UsageWidgetProvider.renderAll(this);
    }
}
