package com.focusledger.android;

public final class LedgerApplication extends android.app.Application {
    @Override public void onCreate() { super.onCreate(); Agent.get(this); }
}
