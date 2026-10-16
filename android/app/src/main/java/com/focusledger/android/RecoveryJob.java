package com.focusledger.android;

import android.app.job.JobParameters;
import android.app.job.JobService;
import android.os.Handler;
import android.os.Looper;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicBoolean;

public final class RecoveryJob extends JobService {
    private final ConcurrentHashMap<Integer, AtomicBoolean> active = new ConcurrentHashMap<>();
    @Override public boolean onStartJob(JobParameters params) {
        Agent agent = Agent.get(this);
        if (!agent.settings.wanted()) return false;
        AtomicBoolean token = new AtomicBoolean(true); active.put(params.getJobId(), token);
        agent.recover(() -> new Handler(Looper.getMainLooper()).post(() -> {
            if (token.compareAndSet(true, false)) { active.remove(params.getJobId(), token); jobFinished(params, false); }
        }));
        return true;
    }
    @Override public boolean onStopJob(JobParameters params) {
        AtomicBoolean token = active.remove(params.getJobId()); if (token != null) token.set(false);
        return Agent.get(this).settings.wanted();
    }
}
