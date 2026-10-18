package com.focusledger.android;

import android.app.Activity;
import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import android.view.ViewGroup;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.LinearLayout;
import java.util.ArrayList;
import java.util.List;

public final class BoardActivity extends Activity {
    private WebView web;
    private final List<String> origins = new ArrayList<>();
    @Override public void onCreate(Bundle state) {
        Config c = Agent.get(this).settings.get();
        boolean dark = Ui.dark(this, c.theme); setTheme(dark ? R.style.AppTheme_Dark : R.style.AppTheme);
        super.onCreate(state); Ui ui = new Ui(this, dark);
        String base = getIntent().getStringExtra("base");
        try { base = Config.normalizeUrl(base == null ? c.primary : base); } catch (Exception e) { finish(); return; }
        origins.add(base); if (!c.primary.isEmpty()) origins.add(c.primary); if (!c.fallback.isEmpty()) origins.add(c.fallback);
        LinearLayout root = ui.column(); root.setBackgroundColor(ui.bg); ui.insets(root);
        LinearLayout bar = ui.row(); bar.setPadding(ui.dp(16), ui.dp(8), ui.dp(16), ui.dp(8));
        Button close = ui.button("返回 App", v -> finish()); ui.icon(close, Icons.BACK);
        Button back = ui.button("后退", v -> { if (web.canGoBack()) web.goBack(); });
        Button reload = ui.button("刷新", v -> web.reload()); ui.icon(reload, Icons.REFRESH);
        Button[] controls = {close, back, reload};
        for (int i = 0; i < controls.length; i++) {
            controls[i].setPadding(ui.dp(10), ui.dp(12), ui.dp(10), ui.dp(12));
            LinearLayout.LayoutParams size = new LinearLayout.LayoutParams(0, -2, i == 0 ? 1.3f : 1f);
            if (i < controls.length - 1) size.setMarginEnd(ui.dp(8)); bar.addView(controls[i], size);
        }
        root.addView(bar);
        web = new WebView(this); root.addView(web, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1));
        WebSettings settings = web.getSettings(); settings.setJavaScriptEnabled(true); settings.setDomStorageEnabled(true);
        settings.setAllowFileAccess(false); settings.setAllowContentAccess(false); settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        settings.setSupportMultipleWindows(false); android.webkit.CookieManager.getInstance().setAcceptThirdPartyCookies(web, false);
        web.setWebViewClient(new WebViewClient() {
            @Override public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                Uri uri = request.getUrl();
                if (!"http".equals(uri.getScheme()) && !"https".equals(uri.getScheme())) return true;
                String origin;
                try { origin = Config.normalizeUrl(new java.net.URI(uri.getScheme(), null, uri.getHost(), uri.getPort(), null, null, null).toString()); }
                catch (Exception e) { return true; }
                if (origins.contains(origin)) return false;
                try { startActivity(new Intent(Intent.ACTION_VIEW, uri)); } catch (RuntimeException ignored) {}
                return true;
            }
        });
        String path = getIntent().getStringExtra("path");
        if (path == null || !path.startsWith("/people/") || path.contains("\\") || path.contains("\n") || path.contains("\r")) path = "/";
        setContentView(root); web.loadUrl(base + path);
        if (android.os.Build.VERSION.SDK_INT >= 33) getOnBackInvokedDispatcher().registerOnBackInvokedCallback(android.window.OnBackInvokedDispatcher.PRIORITY_DEFAULT, this::back);
    }
    private void back() { if (web != null && web.canGoBack()) web.goBack(); else finish(); }
    // Android 9–12 compatibility; API 33+ uses the registered platform callback above.
    @android.annotation.SuppressLint("GestureBackNavigation")
    @Override public void onBackPressed() { back(); }
    @Override protected void onPause() { super.onPause(); if (web != null) web.onPause(); }
    @Override protected void onResume() { super.onResume(); if (web != null) web.onResume(); }
    @Override protected void onDestroy() { if (web != null) { web.stopLoading(); web.destroy(); } super.onDestroy(); }
}
