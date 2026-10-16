package com.focusledger.android;

import android.animation.ValueAnimator;
import android.app.Activity;
import android.content.res.ColorStateList;
import android.content.res.Configuration;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.graphics.drawable.RippleDrawable;
import android.graphics.drawable.StateListDrawable;
import android.os.Build;
import android.text.InputType;
import android.view.Gravity;
import android.view.View;
import android.view.WindowInsets;
import android.widget.Button;
import android.widget.CompoundButton;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.Switch;
import android.widget.TextView;

final class Ui {
    final Activity a; final boolean dark;
    final int bg, card, ink, muted, line, accent, accentSoft, surface;
    Ui(Activity a, boolean dark) {
        this.a = a; this.dark = dark;
        bg = Color.parseColor(dark ? "#171D1C" : "#F5F2EB"); card = Color.parseColor(dark ? "#222B28" : "#FFFEFA");
        ink = Color.parseColor(dark ? "#EAEDE4" : "#293630"); muted = Color.parseColor(dark ? "#ABB6AC" : "#687168");
        line = Color.parseColor(dark ? "#35423B" : "#E4E7DC"); accent = Color.parseColor(dark ? "#F1AD90" : "#A94D39");
        accentSoft = Color.parseColor(dark ? "#45352E" : "#F6E7DE"); surface = Color.parseColor(dark ? "#2C3630" : "#F1F2EA");
        a.getWindow().setBackgroundDrawableResource(dark ? R.color.window_dark : R.color.window_light);
    }
    static boolean dark(Activity a, String theme) { return theme.equals("dark") || (theme.equals("system") && (a.getResources().getConfiguration().uiMode & Configuration.UI_MODE_NIGHT_MASK) == Configuration.UI_MODE_NIGHT_YES); }
    static boolean animationsEnabled() { return ValueAnimator.areAnimatorsEnabled(); }
    int dp(float value) { return (int)(a.getResources().getDisplayMetrics().density * value + .5f); }
    LinearLayout column() { LinearLayout l = new LinearLayout(a); l.setOrientation(LinearLayout.VERTICAL); return l; }
    LinearLayout row() { LinearLayout l = new LinearLayout(a); l.setOrientation(LinearLayout.HORIZONTAL); l.setGravity(Gravity.CENTER_VERTICAL); return l; }
    TextView text(String value, int size, boolean bold) {
        TextView t = new TextView(a); t.setText(value); t.setTextSize(size); t.setTextColor(ink);
        t.setIncludeFontPadding(false); t.setLineSpacing(dp(3), 1.08f);
        t.setTypeface(Typeface.create(bold ? "sans-serif-medium" : "sans-serif", Typeface.NORMAL)); return t;
    }
    TextView muted(String value) { TextView t = text(value, 13, false); t.setTextColor(muted); return t; }
    TextView title(LinearLayout parent, String value) {
        TextView t = text(value, 17, true); t.setPadding(0, 0, 0, dp(12)); t.setAccessibilityHeading(true); parent.addView(t); return t;
    }
    void pageTitle(LinearLayout parent, String title, String subtitle) {
        LinearLayout heading = column(); heading.setPadding(dp(2), dp(2), dp(2), dp(18));
        TextView t = text(title, 23, true); t.setAccessibilityHeading(true); heading.addView(t);
        TextView caption = muted(subtitle); caption.setPadding(0, dp(6), 0, 0); heading.addView(caption); parent.addView(heading);
    }
    void note(LinearLayout parent, String value) { TextView t = muted(value); t.setPadding(0, dp(6), 0, dp(8)); parent.addView(t); }
    GradientDrawable shape(int fill, int border, int radius) {
        GradientDrawable s = new GradientDrawable(); s.setColor(fill); s.setCornerRadius(dp(radius)); if (border != 0) s.setStroke(dp(1), border); return s;
    }
    RippleDrawable ripple(int fill, int border, int radius) {
        return new RippleDrawable(ColorStateList.valueOf(dark ? 0x24FFFFFF : 0x16A94D39), shape(fill, border, radius), shape(Color.WHITE, 0, radius));
    }
    LinearLayout card(LinearLayout parent) {
        LinearLayout box = column(); box.setBackground(shape(card, line, 24)); box.setPadding(dp(20), dp(20), dp(20), dp(20));
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, -2); lp.bottomMargin = dp(14); parent.addView(box, lp); return box;
    }
    Button button(String value, View.OnClickListener listener) { return styledButton(value, listener, surface, ink); }
    Button primary(String value, View.OnClickListener listener) { return styledButton(value, listener, accent, dark ? bg : Color.WHITE); }
    Button quiet(String value, View.OnClickListener listener) { return styledButton(value, listener, Color.TRANSPARENT, accent); }
    private Button styledButton(String value, View.OnClickListener listener, int fill, int textColor) {
        Button b = new Button(a); b.setText(value); b.setTextSize(14); b.setAllCaps(false);
        b.setTypeface(Typeface.create("sans-serif-medium", Typeface.NORMAL)); b.setTextColor(new ColorStateList(
            new int[][]{new int[]{-android.R.attr.state_enabled}, new int[]{}}, new int[]{muted, textColor}));
        b.setBackgroundTintList(null); b.setStateListAnimator(null); b.setElevation(0); b.setBackground(ripple(fill, 0, 15));
        b.setMinWidth(0); b.setMinimumWidth(0); b.setMinHeight(dp(48)); b.setMinimumHeight(dp(48));
        b.setPadding(dp(16), dp(12), dp(16), dp(12)); b.setIncludeFontPadding(false); b.setGravity(Gravity.CENTER);
        b.setOnClickListener(listener); LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, -2); lp.topMargin = dp(10); b.setLayoutParams(lp); return b;
    }
    void icon(Button button, int kind) {
        Icons icon = new Icons(kind, button.getCurrentTextColor()); icon.setBounds(0, 0, dp(18), dp(18));
        button.setCompoundDrawablesRelative(icon, null, null, null); button.setCompoundDrawablePadding(dp(8));
    }
    void trailingIcon(Button button, int kind) {
        Icons icon = new Icons(kind, button.getCurrentTextColor()); icon.setBounds(0, 0, dp(18), dp(18));
        button.setCompoundDrawablesRelative(null, null, icon, null); button.setCompoundDrawablePadding(dp(10));
        button.setGravity(Gravity.START | Gravity.CENTER_VERTICAL);
    }
    Button iconButton(int kind, String description, View.OnClickListener listener) {
        Button b = quiet("", listener); b.setContentDescription(description); b.setPadding(dp(12), dp(12), dp(12), dp(12));
        Icons icon = new Icons(kind, ink); icon.setBounds(0, 0, dp(22), dp(22)); b.setCompoundDrawables(icon, null, null, null);
        b.setBackground(ripple(card, line, 16)); b.setTooltipText(description); b.setLayoutParams(new LinearLayout.LayoutParams(dp(48), dp(48))); return b;
    }
    void actions(LinearLayout parent, Button first, Button second) {
        Configuration configuration = a.getResources().getConfiguration();
        if (configuration.screenWidthDp / configuration.fontScale < 280) {
            LinearLayout stack = column(); stack.addView(first, new LinearLayout.LayoutParams(-1, -2));
            LinearLayout.LayoutParams next = new LinearLayout.LayoutParams(-1, -2); next.topMargin = dp(10); stack.addView(second, next);
            LinearLayout.LayoutParams size = new LinearLayout.LayoutParams(-1, -2); size.topMargin = dp(16); parent.addView(stack, size); return;
        }
        LinearLayout row = row(); LinearLayout.LayoutParams firstSize = new LinearLayout.LayoutParams(0, -2, 1);
        firstSize.setMarginEnd(dp(10)); row.addView(first, firstSize); row.addView(second, new LinearLayout.LayoutParams(0, -2, 1));
        LinearLayout.LayoutParams rowSize = new LinearLayout.LayoutParams(-1, -2); rowSize.topMargin = dp(16); parent.addView(row, rowSize);
    }
    void divider(LinearLayout parent) {
        View v = new View(a); v.setBackgroundColor(line); LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, dp(1));
        lp.topMargin = dp(12); lp.bottomMargin = dp(12); parent.addView(v, lp);
    }
    TextView badge(String value) {
        TextView t = text(value, 11, true); t.setTextColor(accent); t.setBackground(shape(accentSoft, 0, 10));
        t.setPadding(dp(10), dp(6), dp(10), dp(6)); return t;
    }
    EditText field(LinearLayout parent, String label, String value, int type) {
        TextView t = muted(label); t.setPadding(0, dp(14), 0, dp(8)); parent.addView(t);
        EditText input = new EditText(a); input.setSingleLine(true); input.setTextSize(15); input.setTextColor(ink); input.setHintTextColor(muted);
        input.setInputType(type); input.setText(value); input.setSelectAllOnFocus(false); input.setBackgroundTintList(null);
        input.setPadding(dp(14), dp(14), dp(14), dp(14)); input.setMinHeight(dp(52));
        StateListDrawable background = new StateListDrawable(); background.addState(new int[]{android.R.attr.state_focused}, shape(card, accent, 14));
        background.addState(new int[]{}, shape(surface, line, 14)); input.setBackground(background);
        input.setId(View.generateViewId()); t.setLabelFor(input.getId()); parent.addView(input, new LinearLayout.LayoutParams(-1, -2)); return input;
    }
    EditText field(LinearLayout parent, String label, String value) { return field(parent, label, value, InputType.TYPE_CLASS_TEXT); }
    ColorStateList controlColors() {
        return new ColorStateList(new int[][]{new int[]{-android.R.attr.state_enabled}, new int[]{android.R.attr.state_checked}, new int[]{}}, new int[]{line, accent, muted});
    }
    void tint(CompoundButton control) { control.setButtonTintList(controlColors()); }
    Switch toggle(LinearLayout parent, String title, boolean checked) {
        Switch s = new Switch(a); s.setText(title); s.setTextSize(14); s.setTextColor(ink); s.setChecked(checked); s.setPadding(0, dp(12), 0, dp(12));
        s.setThumbTintList(new ColorStateList(new int[][]{new int[]{android.R.attr.state_checked}, new int[]{}}, new int[]{accent, muted}));
        s.setTrackTintList(new ColorStateList(new int[][]{new int[]{android.R.attr.state_checked}, new int[]{}}, new int[]{accentSoft, line}));
        s.setSwitchPadding(dp(14)); s.setMinHeight(dp(52)); parent.addView(s, new LinearLayout.LayoutParams(-1, -2)); return s;
    }
    void insets(View root) {
        root.setOnApplyWindowInsetsListener((v, inset) -> {
            if (Build.VERSION.SDK_INT >= 30) {
                android.graphics.Insets bars = inset.getInsets(WindowInsets.Type.systemBars() | WindowInsets.Type.displayCutout());
                android.graphics.Insets ime = inset.getInsets(WindowInsets.Type.ime()); v.setPadding(bars.left, bars.top, bars.right, Math.max(bars.bottom, ime.bottom));
            } else v.setPadding(inset.getSystemWindowInsetLeft(), inset.getSystemWindowInsetTop(), inset.getSystemWindowInsetRight(), inset.getSystemWindowInsetBottom());
            return inset;
        });
        if (Build.VERSION.SDK_INT >= 30) {
            a.getWindow().getDecorView(); a.getWindow().setDecorFitsSystemWindows(false);
            android.view.WindowInsetsController controller = a.getWindow().getInsetsController();
            if (controller != null) controller.setSystemBarsAppearance(dark ? 0 : android.view.WindowInsetsController.APPEARANCE_LIGHT_STATUS_BARS | android.view.WindowInsetsController.APPEARANCE_LIGHT_NAVIGATION_BARS,
                android.view.WindowInsetsController.APPEARANCE_LIGHT_STATUS_BARS | android.view.WindowInsetsController.APPEARANCE_LIGHT_NAVIGATION_BARS);
        } else {
            a.getWindow().setStatusBarColor(bg); a.getWindow().setNavigationBarColor(bg);
            a.getWindow().getDecorView().setSystemUiVisibility(dark ? 0 : View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR | View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR);
        }
    }
    static String duration(double seconds) { long s = Math.max(0, (long)seconds); return s >= 3600 ? s/3600 + " 小时 " + (s%3600)/60 + " 分" : s/60 + " 分 " + s%60 + " 秒"; }
    static String clock(long millis) { return millis <= 0 ? "尚无记录" : java.time.Instant.ofEpochMilli(millis).atZone(java.time.ZoneId.systemDefault()).format(java.time.format.DateTimeFormatter.ofPattern("MM-dd HH:mm:ss")); }
}
