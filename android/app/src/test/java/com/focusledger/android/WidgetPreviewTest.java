package com.focusledger.android;

import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.view.View;
import org.junit.Assume;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RuntimeEnvironment;
import org.robolectric.Robolectric;
import org.robolectric.annotation.Config;
import org.robolectric.annotation.GraphicsMode;
import java.io.File;
import java.io.FileOutputStream;

@RunWith(org.robolectric.RobolectricTestRunner.class)
@Config(sdk = 30, qualifiers = "zh-rCN-mdpi")
@GraphicsMode(GraphicsMode.Mode.NATIVE)
public class WidgetPreviewTest {
    @Test public void renderSizesAndThemes() throws Exception {
        String destination = System.getProperty("focusledger.widget.preview"); Assume.assumeNotNull(destination);
        Context context = RuntimeEnvironment.getApplication(); WidgetStore store = new WidgetStore(context);
        int[][] sizes = {{110,110}, {160,160}, {320,150}, {320,320}, {580,420}, {160,400}, {500,110}};
        for (boolean dark : new boolean[]{false, true}) for (int[] size : sizes) {
            RuntimeEnvironment.setFontScale(size[0] == 110 ? 1.3f : 1f);
            WidgetStore.Options o = new WidgetStore.Options(); o.primary = "https://example.invalid"; o.theme = dark ? "dark" : "light";
            store.save(101, o); store.success(101, o.identity(), WidgetDataTest.sample());
            View root = WidgetRenderer.render(context, 101, size[0], size[1]).apply(context, null); UsageWidgetTest.layout(root, size[0], size[1]);
            Bitmap bitmap = Bitmap.createBitmap(size[0], size[1], Bitmap.Config.ARGB_8888); root.draw(new Canvas(bitmap));
            File file = new File(destination, (dark ? "dark" : "light") + "-" + size[0] + "x" + size[1] + ".png"); file.getParentFile().mkdirs();
            try (FileOutputStream out = new FileOutputStream(file)) { bitmap.compress(Bitmap.CompressFormat.PNG, 100, out); }
            bitmap.recycle();
        }
        RuntimeEnvironment.setFontScale(1f);
        int id = org.robolectric.Shadows.shadowOf(android.appwidget.AppWidgetManager.getInstance(context)).createWidget(UsageWidgetProvider.class, R.layout.widget_timetable);
        WidgetStore.Options options = new WidgetStore.Options(); options.primary = "https://example.invalid"; store.save(id, options); store.success(id, options.identity(), WidgetDataTest.sample());
        android.content.Intent config = new android.content.Intent(context, WidgetConfigActivity.class).putExtra(android.appwidget.AppWidgetManager.EXTRA_APPWIDGET_ID, id);
        try (var activity = Robolectric.buildActivity(WidgetConfigActivity.class, config).setup()) { page(activity.get(), destination, "settings"); }
        android.content.Intent detail = new android.content.Intent(context, WidgetDetailActivity.class).putExtra(android.appwidget.AppWidgetManager.EXTRA_APPWIDGET_ID, id).putExtra("user", "alice").putExtra("device", "phone");
        try (var activity = Robolectric.buildActivity(WidgetDetailActivity.class, detail).setup()) { page(activity.get(), destination, "detail"); }
    }
    private void page(android.app.Activity activity, String destination, String name) throws Exception {
        View root = activity.findViewById(android.R.id.content); UsageWidgetTest.layout(root, 393, 852);
        Bitmap bitmap = Bitmap.createBitmap(393, 852, Bitmap.Config.ARGB_8888); root.draw(new Canvas(bitmap));
        try (FileOutputStream out = new FileOutputStream(new File(destination, name + ".png"))) { bitmap.compress(Bitmap.CompressFormat.PNG, 100, out); }
        bitmap.recycle();
    }
}
