package com.focusledger.android;

import android.view.View;
import android.view.animation.PathInterpolator;
import android.widget.FrameLayout;

final class PageMotion {
    private PageMotion() {}
    static void show(FrameLayout host, View previous, View incoming, int direction, Ui ui, boolean animate) {
        // Remove stale completion actions before cancelling a rapid sequence of switches.
        settle(host); host.removeAllViews();
        boolean moving = animate && Ui.animationsEnabled() && previous != null && host.isLaidOut();
        if (moving) {
            previous.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO_HIDE_DESCENDANTS);
            host.addView(previous, new FrameLayout.LayoutParams(-1, -1));
        }
        host.addView(incoming, new FrameLayout.LayoutParams(-1, -1));
        if (!moving) return;
        incoming.setAlpha(0f); incoming.setTranslationX(direction * ui.dp(28)); incoming.setTranslationY(direction == 0 ? ui.dp(8) : 0);
        previous.animate().alpha(0f).translationX(-direction * ui.dp(18)).setDuration(160)
            .withEndAction(() -> { if (previous.getParent() == host) host.removeView(previous); }).start();
        incoming.animate().alpha(1f).translationX(0f).translationY(0f).setDuration(280)
            .setInterpolator(new PathInterpolator(.22f, 1f, .36f, 1f)).start();
    }
    static void settle(FrameLayout host) {
        for (int i = 0; i < host.getChildCount(); i++) {
            View child = host.getChildAt(i); child.animate().withEndAction(null).cancel();
            child.setAlpha(1f); child.setTranslationX(0); child.setTranslationY(0);
        }
        while (host.getChildCount() > 1) host.removeViewAt(0);
    }
}
