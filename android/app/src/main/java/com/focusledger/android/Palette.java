package com.focusledger.android;

import java.math.BigInteger;
import java.util.List;
import java.util.Locale;

final class Palette {
    static final List<String> IDS = java.util.Arrays.asList("slate", "teal", "olive", "ochre", "terracotta", "rose", "mauve", "indigo", "steel", "sage", "cocoa", "plum");
    static final String[] NAMES = {"雾蓝", "灰青", "橄榄", "赭黄", "陶土", "豆沙", "灰紫", "靛灰", "钢蓝", "鼠尾草", "可可", "梅灰"};
    static final String[] LIGHT = {"#597486", "#487f7a", "#7a8050", "#a08142", "#ac6e52", "#a06472", "#886f92", "#65719b", "#4b829a", "#6d8b69", "#876d59", "#936582"};
    static final String[] DARK = {"#8faebe", "#83b5a9", "#b0b77b", "#ccb276", "#d49a7b", "#ce94a1", "#b8a1c2", "#9faacf", "#86b8cb", "#a0bc96", "#baa18a", "#c799b5"};
    static String defaultId(String pkg) {
        String key = pkg.trim().toLowerCase(Locale.ROOT); if (key.endsWith(".exe")) key = key.substring(0, key.length() - 4);
        return IDS.get(new BigInteger(Config.sha256(key), 16).mod(BigInteger.valueOf(IDS.size())).intValue());
    }
    static int color(Config c, String pkg, boolean dark) {
        String id = c.colors.optString(pkg.toLowerCase(Locale.ROOT), defaultId(pkg)); int index = IDS.indexOf(id); if (index < 0) index = 0;
        return android.graphics.Color.parseColor((dark ? DARK : LIGHT)[index]);
    }
}
