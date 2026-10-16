package com.focusledger.android;

import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.os.Looper;
import android.view.View;
import org.junit.Assume;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.Robolectric;
import org.robolectric.RuntimeEnvironment;
import org.robolectric.Shadows;
import org.robolectric.annotation.Config;
import org.robolectric.annotation.GraphicsMode;
import org.robolectric.annotation.LooperMode;
import org.robolectric.android.controller.ActivityController;
import java.io.File;
import java.io.FileOutputStream;
import java.time.Duration;
import java.util.List;

/** Optional native Android rendering, using isolated sample data and no server connection. */
@RunWith(org.robolectric.RobolectricTestRunner.class)
@Config(sdk = 30, qualifiers = "zh-rCN-w393dp-h852dp-mdpi")
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@LooperMode(LooperMode.Mode.PAUSED)
public class VisualPreviewTest {
    @Test public void renderLightPages() throws Exception { render(false, 393, 852, 1f, "light"); }
    @Test public void renderDarkPages() throws Exception { render(true, 393, 852, 1f, "dark"); }
    @Test public void renderSmallScreenWithLargeText() throws Exception { render(false, 320, 720, 1.5f, "large-text"); }

    private void render(boolean dark, int width, int height, float fontScale, String name) throws Exception {
        String destination = System.getProperty("focusledger.preview"); Assume.assumeNotNull(destination);
        RuntimeEnvironment.setQualifiers("zh-rCN-w" + width + "dp-h" + height + "dp-" + (dark ? "night" : "notnight") + "-mdpi");
        RuntimeEnvironment.setFontScale(fontScale);
        android.os.SystemClock.setCurrentTimeMillis(MainActivity.todayStart() + 16 * 3600000);
        try (ActivityController<MainActivity> controller = Robolectric.buildActivity(MainActivity.class).setup()) {
            MainActivity a = controller.get(); com.focusledger.android.Config sample = a.agent.settings.get(); sample.deviceName = "Redmi K90"; sample.username = "Mike";
            sample.mode = "xiaomi"; sample.aliases.put("com.sample.reader", "阅读"); sample.aliases.put("com.sample.music", "音乐"); sample.aliases.put("com.sample.notes", "笔记");
            a.agent.settings.save(sample);
            long start = MainActivity.todayStart() + 8 * 3600000;
            a.agent.store.commit(sample.scope, null, List.of(new LedgerStore.Slice("com.sample.reader", start, start + 6120000),
                new LedgerStore.Slice("com.sample.music", start + 6200000, start + 8120000),
                new LedgerStore.Slice("com.sample.notes", start + 8200000, start + 9100000)), List.of(), a.agent.reader);
            a.render();
            for (int i = 0; i < 5; i++) {
                a.show(i); Shadows.shadowOf(Looper.getMainLooper()).idleFor(Duration.ofMillis(700)); PageMotion.settle(a.pages); a.nav.settle();
                View root = a.findViewById(android.R.id.content);
                root.measure(View.MeasureSpec.makeMeasureSpec(width, View.MeasureSpec.EXACTLY), View.MeasureSpec.makeMeasureSpec(height, View.MeasureSpec.EXACTLY));
                root.layout(0, 0, width, height); root.getViewTreeObserver().dispatchOnPreDraw();
                Bitmap bitmap = Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888); Canvas canvas = new Canvas(bitmap); root.draw(canvas);
                File file = new File(destination, name + "-" + i + ".png"); file.getParentFile().mkdirs();
                try (FileOutputStream out = new FileOutputStream(file)) { bitmap.compress(Bitmap.CompressFormat.PNG, 100, out); }
                bitmap.recycle();
            }
        }
    }
}
