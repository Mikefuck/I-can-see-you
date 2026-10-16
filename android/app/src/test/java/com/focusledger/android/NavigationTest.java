package com.focusledger.android;

import android.animation.ValueAnimator;
import android.os.Looper;
import android.view.View;
import org.junit.After;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.Robolectric;
import org.robolectric.Shadows;
import org.robolectric.annotation.Config;
import org.robolectric.annotation.LooperMode;
import org.robolectric.android.controller.ActivityController;
import org.robolectric.util.ReflectionHelpers;
import java.time.Duration;
import static org.junit.Assert.*;

@RunWith(org.robolectric.RobolectricTestRunner.class)
@Config(sdk = {28, 30, 36})
@LooperMode(LooperMode.Mode.PAUSED)
public class NavigationTest {
    @Before public void enableMotion() { durationScale(1f); }
    @After public void restoreMotion() { durationScale(1f); }

    @Test public void rapidNavigationFinishesOnLastPageAndRemovesOutgoingPages() {
        try (ActivityController<MainActivity> controller = Robolectric.buildActivity(MainActivity.class).setup()) {
            MainActivity a = controller.get(); layout(a);
            a.show(2); assertTrue(a.scroll.getTranslationX() > 0); assertEquals(2, a.pages.getChildCount());
            a.show(4); a.show(1); assertTrue(a.scroll.getTranslationX() < 0);
            Shadows.shadowOf(Looper.getMainLooper()).idleFor(Duration.ofMillis(700));
            assertEquals(1, a.selected); assertEquals(1, a.nav.selectedTab()); assertEquals(1, a.pages.getChildCount());
            assertSame(a.scroll, a.pages.getChildAt(0)); assertEquals(1f, a.scroll.getAlpha(), 0f);
            assertEquals(0f, a.scroll.getTranslationX(), 0f); assertTrue(a.body.getChildCount() > 0);
        }
    }
    @Test public void disabledSystemAnimationsShowCompletePageImmediately() {
        durationScale(0f);
        try (ActivityController<MainActivity> controller = Robolectric.buildActivity(MainActivity.class).setup()) {
            MainActivity a = controller.get(); layout(a); a.show(3);
            assertEquals(3, a.selected); assertEquals(3, a.nav.selectedTab()); assertEquals(1, a.pages.getChildCount());
            assertEquals(1f, a.scroll.getAlpha(), 0f); assertEquals(0f, a.scroll.getTranslationX(), 0f);
        }
    }
    @Test public void leavingAppMidTransitionKeepsCurrentPageVisibleOnReturn() {
        try (ActivityController<MainActivity> controller = Robolectric.buildActivity(MainActivity.class).setup()) {
            MainActivity a = controller.get(); layout(a); a.show(4); controller.pause();
            assertEquals(1, a.pages.getChildCount()); assertSame(a.scroll, a.pages.getChildAt(0));
            assertEquals(1f, a.scroll.getAlpha(), 0f); assertEquals(0f, a.scroll.getTranslationX(), 0f);
            controller.resume(); Shadows.shadowOf(Looper.getMainLooper()).idleFor(Duration.ofMillis(700));
            assertEquals(4, a.selected); assertEquals(1, a.pages.getChildCount()); assertSame(a.scroll, a.pages.getChildAt(0));
        }
    }
    static void layout(MainActivity a) {
        View root = a.findViewById(android.R.id.content);
        root.measure(View.MeasureSpec.makeMeasureSpec(a.ui.dp(360), View.MeasureSpec.EXACTLY), View.MeasureSpec.makeMeasureSpec(a.ui.dp(780), View.MeasureSpec.EXACTLY));
        root.layout(0, 0, root.getMeasuredWidth(), root.getMeasuredHeight());
    }
    private static void durationScale(float scale) {
        ReflectionHelpers.callStaticMethod(ValueAnimator.class, "setDurationScale", ReflectionHelpers.ClassParameter.from(float.class, scale));
    }
}
