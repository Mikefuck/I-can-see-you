package com.focusledger.android;

import android.graphics.Canvas;
import android.graphics.ColorFilter;
import android.graphics.Paint;
import android.graphics.Path;
import android.graphics.PixelFormat;
import android.graphics.drawable.Drawable;

/** Density-independent line icons shared by navigation and actions. */
final class Icons extends Drawable {
    static final int OVERVIEW = 0, HISTORY = 1, CONNECT = 2, SHIELD = 3, SERVER = 4;
    static final int THEME = 5, PLAY = 6, PAUSE = 7, UPLOAD = 8, ARROW = 9, LOCK = 10, BACK = 11, REFRESH = 12;
    private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final int kind;
    Icons(int kind, int color) {
        this.kind = kind; paint.setColor(color); paint.setStyle(Paint.Style.STROKE);
        paint.setStrokeWidth(1.8f); paint.setStrokeCap(Paint.Cap.ROUND); paint.setStrokeJoin(Paint.Join.ROUND);
    }
    void color(int value) { paint.setColor(value); invalidateSelf(); }
    @Override public void draw(Canvas canvas) {
        int save = canvas.save(); canvas.translate(getBounds().left, getBounds().top);
        canvas.scale(getBounds().width() / 24f, getBounds().height() / 24f);
        switch (kind) {
            case OVERVIEW -> {
                canvas.drawRoundRect(3, 3, 10, 12, 2, 2, paint); canvas.drawRoundRect(14, 3, 21, 8, 2, 2, paint);
                canvas.drawRoundRect(3, 16, 10, 21, 2, 2, paint); canvas.drawRoundRect(14, 12, 21, 21, 2, 2, paint);
            }
            case HISTORY -> { canvas.drawCircle(12, 12, 9, paint); line(canvas, 12, 7, 12, 12, 16, 14); }
            case CONNECT -> {
                line(canvas, 10, 7, 12, 5, 15, 5, 17, 7, 17, 10, 14, 13);
                line(canvas, 14, 17, 12, 19, 9, 19, 7, 17, 7, 14, 10, 11); canvas.drawLine(9, 15, 15, 9, paint);
            }
            case SHIELD -> { line(canvas, 12, 3, 20, 6, 20, 12, 18, 17, 12, 21, 6, 17, 4, 12, 4, 6, 12, 3); line(canvas, 13, 8, 10, 12, 14, 12, 11, 16); }
            case SERVER -> {
                canvas.drawRoundRect(3, 3, 21, 10, 2, 2, paint); canvas.drawRoundRect(3, 14, 21, 21, 2, 2, paint);
                canvas.drawPoint(7, 6.5f, paint); canvas.drawPoint(7, 17.5f, paint);
                canvas.drawLine(12, 6.5f, 17, 6.5f, paint); canvas.drawLine(12, 17.5f, 17, 17.5f, paint);
            }
            case THEME -> {
                canvas.drawCircle(12, 12, 4, paint);
                for (int i = 0; i < 8; i++) { canvas.save(); canvas.rotate(i * 45, 12, 12); canvas.drawLine(12, 2, 12, 4, paint); canvas.restore(); }
            }
            case PLAY -> line(canvas, 8, 4, 20, 12, 8, 20, 8, 4);
            case PAUSE -> { canvas.drawLine(8, 5, 8, 19, paint); canvas.drawLine(16, 5, 16, 19, paint); }
            case UPLOAD -> { line(canvas, 7, 9, 12, 4, 17, 9); canvas.drawLine(12, 4, 12, 16, paint); line(canvas, 4, 16, 4, 20, 20, 20, 20, 16); }
            case ARROW -> { canvas.drawLine(4, 12, 20, 12, paint); line(canvas, 14, 6, 20, 12, 14, 18); }
            case BACK -> { canvas.drawLine(4, 12, 20, 12, paint); line(canvas, 10, 6, 4, 12, 10, 18); }
            case LOCK -> { canvas.drawRoundRect(5, 10, 19, 21, 2, 2, paint); canvas.drawArc(8, 3, 16, 17, 180, 180, false, paint); canvas.drawLine(12, 14, 12, 17, paint); }
            case REFRESH -> { canvas.drawArc(4, 4, 20, 20, 35, 290, false, paint); line(canvas, 20, 4, 20, 10, 14, 10); }
            default -> { }
        }
        canvas.restoreToCount(save);
    }
    private void line(Canvas c, float... points) {
        Path p = new Path(); p.moveTo(points[0], points[1]);
        for (int i = 2; i < points.length; i += 2) p.lineTo(points[i], points[i + 1]); c.drawPath(p, paint);
    }
    @Override public void setAlpha(int alpha) { paint.setAlpha(alpha); invalidateSelf(); }
    @Override public void setColorFilter(ColorFilter filter) { paint.setColorFilter(filter); invalidateSelf(); }
    @Override public int getOpacity() { return PixelFormat.TRANSLUCENT; }
    @Override public int getIntrinsicWidth() { return 24; }
    @Override public int getIntrinsicHeight() { return 24; }
}
