package com.focusledger.android;

import android.app.Application;
import android.app.job.JobScheduler;
import android.appwidget.AppWidgetManager;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.os.Bundle;
import android.view.View;
import android.view.ViewGroup;
import android.widget.TextView;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.Robolectric;
import org.robolectric.RuntimeEnvironment;
import org.robolectric.Shadows;
import org.robolectric.annotation.Config;
import org.robolectric.android.controller.ActivityController;
import org.robolectric.util.ReflectionHelpers;
import java.time.ZoneId;
import static org.junit.Assert.*;

@RunWith(org.robolectric.RobolectricTestRunner.class)
@Config(sdk = {28, 30, 36}, qualifiers = "zh-rCN-mdpi")
public class UsageWidgetTest {
    private final Context context = RuntimeEnvironment.getApplication();
    int widget() { return Shadows.shadowOf(AppWidgetManager.getInstance(context)).createWidget(UsageWidgetProvider.class, R.layout.widget_timetable); }
    void sample(int id) throws Exception {
        WidgetStore.Options o = new WidgetStore.Options(); o.primary = "https://example.invalid";
        WidgetStore store = new WidgetStore(context); store.save(id, o); store.success(id, o.identity(), WidgetDataTest.sample());
    }
    @Test public void standardProviderNeedsNoXiaomiIdentityOrCollector() throws Exception {
        android.content.pm.ActivityInfo info = context.getPackageManager().getReceiverInfo(new ComponentName(context, UsageWidgetProvider.class), PackageManager.GET_META_DATA);
        assertFalse(info.exported); assertFalse(info.metaData.containsKey("miuiWidget")); assertEquals(context.getPackageName(), info.processName);
        ReflectionHelpers.setStaticField(Agent.class, "instance", null); ((Application)context).onCreate();
        widget(); assertNull(ReflectionHelpers.getStaticField(Agent.class, "instance"));
        assertEquals(2, context.getSystemService(JobScheduler.class).getAllPendingJobs().size());
    }
    @Test public void smallestCardAndLargeFontsKeepRowAndActionsInsideBounds() throws Exception {
        int id = widget(); sample(id); RuntimeEnvironment.setFontScale(1.3f);
        View root = WidgetRenderer.render(context, id, 110, 110).apply(context, null); layout(root, 110, 110);
        View rows = root.findViewById(R.id.widget_rows), footer = root.findViewById(R.id.widget_footer);
        assertTrue("rows height=" + rows.getHeight(), rows.getHeight() >= 34);
        assertTrue("footer bottom=" + footer.getBottom(), footer.getBottom() <= 110);
        assertTrue("footer top=" + footer.getTop() + ", rows bottom=" + rows.getBottom(), footer.getTop() >= rows.getBottom());
        assertTrue("row content=" + ((ViewGroup)rows).getChildAt(0).getBottom() + ", available=" + rows.getHeight(), ((ViewGroup)rows).getChildAt(0).getBottom() <= rows.getHeight());
        assertEquals(1, ((ViewGroup)rows).getChildCount());
        assertEquals(View.GONE, root.findViewById(R.id.widget_device_status).getVisibility());
        root.findViewById(R.id.widget_heading).performClick();
        assertEquals(WidgetConfigActivity.class.getName(), Shadows.shadowOf((Application)context).getNextStartedActivity().getComponent().getClassName());
    }
    @Test public void paginationAndFiltersStayIndependentAndDetailsKeepDeviceIdentity() throws Exception {
        int first = widget(), second = widget(); sample(first); sample(second);
        new UsageWidgetProvider().onReceive(context, new Intent(context, UsageWidgetProvider.class).setAction(UsageWidgetProvider.PAGE)
            .putExtra(AppWidgetManager.EXTRA_APPWIDGET_ID, first).putExtra("page", 1));
        assertEquals(1, new WidgetStore(context).page(first)); assertEquals(0, new WidgetStore(context).page(second));
        View root = WidgetRenderer.render(context, first, 160, 110).apply(context, null);
        root.findViewById(R.id.widget_device_row).performClick();
        Intent intent = Shadows.shadowOf((Application)context).getNextStartedActivity();
        assertEquals("pc", intent.getStringExtra("device")); assertEquals("alice", intent.getStringExtra("user"));
        assertEquals(WidgetDetailActivity.class.getName(), intent.getComponent().getClassName());
        new WidgetStore(context).page(first, 0);
        View firstPage = WidgetRenderer.render(context, first, 160, 110).apply(context, null);
        firstPage.findViewById(R.id.widget_previous).performClick();
        java.util.List<Intent> broadcasts = Shadows.shadowOf((Application)context).getBroadcastIntents();
        assertEquals(2, broadcasts.get(broadcasts.size() - 1).getIntExtra("page", -1));
    }
    @Test public void authenticationFailureClearsPrivateSnapshotAndLateResultsCannotCrossServers() throws Exception {
        int id = widget(); sample(id); WidgetStore store = new WidgetStore(context); String old = store.options(id).identity();
        store.failure(id, old, "授权已失效", true); assertNull(store.data(id)); assertEquals(0, store.updated(id));
        WidgetStore.Options changed = store.options(id); changed.primary = "https://another.invalid"; store.save(id, changed);
        store.success(id, old, WidgetDataTest.sample()); assertNull(store.data(id));
    }
    @Test public void resizingAndNightThemeInflateUsingSupportedNativeViews() throws Exception {
        int id = widget(); sample(id);
        for (int[] size : new int[][]{{320, 150}, {320, 320}, {160, 400}, {580, 420}}) {
            View root = WidgetRenderer.render(context, id, size[0], size[1]).apply(context, null); layout(root, size[0], size[1]);
            ViewGroup rows = root.findViewById(R.id.widget_rows);
            assertTrue(rows.getChildCount() >= 1);
            assertTrue(rows.getChildAt(rows.getChildCount() - 1).getBottom() <= rows.getHeight());
        }
        WidgetStore store = new WidgetStore(context); WidgetStore.Options options = store.options(id); options.theme = "dark"; store.save(id, options); store.success(id, options.identity(), WidgetDataTest.sample());
        View dark = WidgetRenderer.render(context, id, 320, 320).apply(context, null);
        assertEquals(0xffe6e3d5, ((TextView)dark.findViewById(R.id.widget_device_name)).getCurrentTextColor());
        Bundle sizes = new Bundle(); sizes.putInt(AppWidgetManager.OPTION_APPWIDGET_MIN_WIDTH, 110); sizes.putInt(AppWidgetManager.OPTION_APPWIDGET_MAX_HEIGHT, 110);
        AppWidgetManager.getInstance(context).updateAppWidgetOptions(id, sizes); UsageWidgetProvider.render(context, id);
    }
    @Test public void configCancelAndDeleteDoNotEnableTracking() {
        try (ActivityController<WidgetConfigActivity> controller = Robolectric.buildActivity(WidgetConfigActivity.class).setup()) {
            assertFalse(controller.get().isFinishing()); assertFalse(Agent.get(context).settings.wanted());
        }
        int id = widget(); new UsageWidgetProvider().onDeleted(context, new int[]{id});
        assertFalse(new WidgetStore(context).options(id).configured);
    }
    static void layout(View root, int width, int height) {
        root.measure(View.MeasureSpec.makeMeasureSpec(width, View.MeasureSpec.EXACTLY), View.MeasureSpec.makeMeasureSpec(height, View.MeasureSpec.EXACTLY)); root.layout(0, 0, width, height);
    }
}
