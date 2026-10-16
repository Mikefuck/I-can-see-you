package com.focusledger.android;

import android.animation.ValueAnimator;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.graphics.Typeface;
import android.view.Gravity;
import android.view.View;
import android.view.accessibility.AccessibilityNodeInfo;
import android.view.animation.PathInterpolator;
import android.widget.FrameLayout;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.TextView;
import java.util.function.IntConsumer;

/** One moving selection indicator on a single navigation surface. */
final class BottomNavigation extends FrameLayout {
    static final String[] LABELS = {"总览", "记录", "连接", "保活", "服务端"};
    private final Ui ui;
    private final View[] items = new View[LABELS.length];
    private final TextView[] labels = new TextView[LABELS.length];
    private final Icons[] icons = new Icons[LABELS.length];
    private final Paint indicator = new Paint(Paint.ANTI_ALIAS_FLAG);
    private ValueAnimator motion;
    private float position;
    private int selected;
    BottomNavigation(Ui ui, IntConsumer onSelect) {
        super(ui.a); this.ui = ui; setWillNotDraw(false);
        setBackground(ui.shape(ui.card, ui.line, 26)); indicator.setColor(ui.accentSoft);
        setElevation(ui.dp(3)); setOutlineAmbientShadowColor(0x12000000); setOutlineSpotShadowColor(0x12000000);
        LinearLayout row = ui.row(); row.setPadding(ui.dp(4), 0, ui.dp(4), 0); addView(row, new FrameLayout.LayoutParams(-1, -1));
        for (int i = 0; i < LABELS.length; i++) {
            final int index = i;
            LinearLayout item = new LinearLayout(ui.a) {
                @Override public void onInitializeAccessibilityNodeInfo(AccessibilityNodeInfo info) {
                    super.onInitializeAccessibilityNodeInfo(info); info.setClassName(android.widget.Button.class.getName());
                    info.setCollectionItemInfo(AccessibilityNodeInfo.CollectionItemInfo.obtain(0, 1, index, 1, false, isSelected()));
                }
            };
            item.setOrientation(LinearLayout.VERTICAL); item.setGravity(Gravity.CENTER);
            item.setFocusable(true); item.setContentDescription(LABELS[i]); item.setBackground(ui.ripple(0, 0, 20));
            icons[i] = new Icons(i, ui.muted); ImageView icon = new ImageView(ui.a); icon.setImageDrawable(icons[i]);
            icon.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO); item.addView(icon, new LinearLayout.LayoutParams(ui.dp(22), ui.dp(30)));
            labels[i] = ui.text(LABELS[i], 11, false); labels[i].setMaxLines(1); labels[i].setGravity(Gravity.CENTER);
            labels[i].setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);
            LinearLayout.LayoutParams labelSize = new LinearLayout.LayoutParams(-1, -2); labelSize.topMargin = ui.dp(4); item.addView(labels[i], labelSize);
            item.setOnClickListener(v -> onSelect.accept(index)); items[i] = item;
            row.addView(item, new LinearLayout.LayoutParams(0, -1, 1));
        }
        select(0, false);
    }
    void select(int index, boolean animate) {
        selected = index;
        for (int i = 0; i < items.length; i++) {
            boolean active = i == index; items[i].setSelected(active);
            icons[i].color(active ? ui.accent : ui.muted); labels[i].setTextColor(active ? ui.accent : ui.muted);
            labels[i].setTypeface(Typeface.DEFAULT, active ? Typeface.BOLD : Typeface.NORMAL);
        }
        if (motion != null) motion.cancel();
        if (!animate || !Ui.animationsEnabled() || !isLaidOut()) { position = index; invalidate(); return; }
        motion = ValueAnimator.ofFloat(position, index); motion.setDuration(280);
        motion.setInterpolator(new PathInterpolator(.22f, 1f, .36f, 1f));
        motion.addUpdateListener(value -> { position = (float)value.getAnimatedValue(); invalidate(); }); motion.start();
    }
    int selectedTab() { return selected; }
    @Override protected void onDraw(Canvas canvas) {
        super.onDraw(canvas); float cell = (getWidth() - ui.dp(8)) / (float)LABELS.length;
        float center = ui.dp(4) + cell * (position + .5f);
        float top = (getHeight() - (ui.dp(34) + labels[0].getPaint().getFontSpacing())) / 2f;
        float half = Math.min(ui.dp(27), cell / 2f - ui.dp(3));
        canvas.drawRoundRect(center - half, top, center + half, top + ui.dp(30), ui.dp(15), ui.dp(15), indicator);
    }
    void settle() { if (motion != null) motion.cancel(); position = selected; invalidate(); }
    @Override protected void onDetachedFromWindow() { settle(); super.onDetachedFromWindow(); }
    @Override public void onInitializeAccessibilityNodeInfo(AccessibilityNodeInfo info) {
        super.onInitializeAccessibilityNodeInfo(info);
        info.setCollectionInfo(AccessibilityNodeInfo.CollectionInfo.obtain(1, LABELS.length, false, AccessibilityNodeInfo.CollectionInfo.SELECTION_MODE_SINGLE));
    }
}
