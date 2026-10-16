package com.focusledger.android;

import android.content.Intent;
import android.view.View;
import android.view.ViewGroup;
import android.widget.TextView;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.Robolectric;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.RuntimeEnvironment;
import org.robolectric.annotation.Config;
import org.robolectric.android.controller.ActivityController;
import static org.junit.Assert.*;

@RunWith(RobolectricTestRunner.class)
@Config(sdk = {28, 30, 36})
public class StartupTest {
    @Test public void freshInstallOpensWithoutPermissionsAndAllTabsRender() {
        try (ActivityController<MainActivity> controller = Robolectric.buildActivity(MainActivity.class).setup()) {
            MainActivity activity = controller.get();
            assertTrue(containsText(activity.body, "先连接你的服务器"));
            assertFalse(activity.agent.settings.wanted());
            assertNull(activity.agent.service);
            for (int tab = 1; tab < 5; tab++) {
                activity.show(tab);
                assertTrue(activity.body.getChildCount() > 0);
            }
            activity.show(0);
            assertTrue(containsText(activity.body, "先连接你的服务器"));
        }
    }

    @Test @Config(qualifiers = "night") public void darkThemeColdStartOpens() {
        try (ActivityController<MainActivity> controller = Robolectric.buildActivity(MainActivity.class).setup()) {
            assertTrue(controller.get().ui.dark);
            assertTrue(containsText(controller.get().body, "先连接你的服务器"));
        }
    }

    @Test public void recreatingWindowRestoresSelectedTab() {
        try (ActivityController<MainActivity> controller = Robolectric.buildActivity(MainActivity.class).setup()) {
            controller.get().show(2);
            controller.recreate();
            assertEquals(2, controller.get().selected);
            assertTrue(controller.get().body.getChildCount() > 0);
        }
    }

    @Test public void boardCreatesItsOwnWindow() {
        Intent intent = new Intent(RuntimeEnvironment.getApplication(), BoardActivity.class)
            .putExtra("base", "https://example.invalid");
        try (ActivityController<BoardActivity> controller = Robolectric.buildActivity(BoardActivity.class, intent).setup()) {
            assertFalse(controller.get().isFinishing());
            assertTrue(containsText(controller.get().findViewById(android.R.id.content), "返回 App"));
        }
    }

    private static boolean containsText(View view, String text) {
        if (view instanceof TextView label && label.getText().toString().contains(text)) return true;
        if (view instanceof ViewGroup group) {
            for (int i = 0; i < group.getChildCount(); i++) if (containsText(group.getChildAt(i), text)) return true;
        }
        return false;
    }
}
