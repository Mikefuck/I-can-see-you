package com.focusledger.android;

import org.junit.Test;
import java.util.ArrayList;
import java.util.List;
import static org.junit.Assert.*;

public class UsageReducerTest {
    record Span(String pkg, long start, long end) {}
    private UsageReducer reducer(List<Span> out) { return new UsageReducer(0, true, true, (p,s,e) -> out.add(new Span(p,s,e))); }
    private long duration(List<Span> out) { return out.stream().mapToLong(s -> s.end-s.start).sum(); }
    @Test public void savesThirtySecondSegmentsWithoutOneSecondRows() {
        List<Span> out = new ArrayList<>(); UsageReducer r = reducer(out); r.event(1, "reader", 1000);
        for (int i = 2; i <= 60; i++) r.advance(i*1000L);
        assertEquals(1, out.size()); assertEquals(new Span("reader", 1000, 31000), out.get(0));
        r.stop(61000); assertEquals(2, out.size()); assertEquals(60000, duration(out));
    }
    @Test public void appChangeClosesOnlyThePreviousApp() {
        List<Span> out = new ArrayList<>(); UsageReducer r = reducer(out);
        r.event(1, "a", 1000); r.event(1, "b", 6000); r.event(2, "a", 6500); r.stop(9000);
        assertEquals(List.of(new Span("a",1000,6000), new Span("b",6000,9000)), out);
    }
    @Test public void lockedScreenNeverContributesUsage() {
        List<Span> out = new ArrayList<>(); UsageReducer r = reducer(out);
        r.event(1,"a",1000); r.event(16,null,5000); r.event(15,null,50000); r.advance(60000);
        assertNull(r.active()); assertEquals(4000,duration(out));
        r.event(18,null,61000); r.stop(65000); assertEquals(8000,duration(out));
    }
    @Test public void keyguardStopsUsageEvenWithScreenOn() {
        List<Span> out = new ArrayList<>(); UsageReducer r = reducer(out);
        r.event(1,"a",1000); r.event(17,null,2000); r.advance(90000); r.stop(90000);
        assertEquals(1000,duration(out));
    }
    @Test public void restoreAndReplayDoesNotCountCommittedTimeAgain() {
        List<Span> out = new ArrayList<>(); UsageReducer r = reducer(out); r.event(1,"a",1000); r.advance(41000);
        assertEquals(30000,duration(out));
        UsageReducer restored = new UsageReducer(r.json(), (p,s,e) -> out.add(new Span(p,s,e)));
        restored.event(1,"b",46000); restored.stop(51000);
        assertEquals(50000,duration(out)); assertEquals(3,out.size());
        assertEquals(new Span("a",31000,46000),out.get(1));
    }
    @Test public void anUncommittedReplayProducesTheSameSlices() {
        List<Span> committed = new ArrayList<>(); UsageReducer r = reducer(committed); r.event(1,"a",1000); r.advance(31000);
        org.json.JSONObject checkpoint = r.json(); List<Span> first = new ArrayList<>(), second = new ArrayList<>();
        UsageReducer attempt = new UsageReducer(checkpoint, (p,s,e)-> first.add(new Span(p,s,e)));
        UsageReducer retry = new UsageReducer(checkpoint, (p,s,e)-> second.add(new Span(p,s,e)));
        attempt.event(1,"b",50000); attempt.advance(90000); retry.event(1,"b",50000); retry.advance(90000);
        assertEquals(first,second);
    }
    @Test public void shutdownAndStartupDoNotExtendTheLastApp() {
        List<Span> out = new ArrayList<>(); UsageReducer r = reducer(out); r.event(1,"a",1000); r.event(26,null,3000);
        r.event(27,null,100000); r.event(15,null,101000); r.event(18,null,102000); r.stop(120000);
        assertEquals(2000,duration(out)); assertNull(r.active());
    }
    @Test public void latePausedEventFromOtherAppIsIgnored() {
        List<Span> out = new ArrayList<>(); UsageReducer r = reducer(out); r.event(1,"a",1000); r.event(1,"b",2000);
        r.event(2,"a",3000); assertEquals("b",r.active()); r.stop(4000); assertEquals(3000,duration(out));
    }
    @Test public void exactBoundaryDoesNotCreateZeroLengthRecord() {
        List<Span> out = new ArrayList<>(); UsageReducer r = reducer(out); r.event(1,"a",0); r.event(1,"b",30000); r.stop(30000);
        assertEquals(1,out.size()); assertEquals(30000,duration(out));
    }
    @Test(expected=IllegalArgumentException.class) public void clockRollbackCannotProduceNegativeDuration() {
        UsageReducer r = reducer(new ArrayList<>()); r.advance(2000); r.advance(1000);
    }
    @Test public void sameTimestampEventsAreAppliedInOrder() {
        List<Span> out = new ArrayList<>(); UsageReducer r = reducer(out); r.event(1,"a",1000); r.event(2,"a",2000); r.event(1,"b",2000); r.stop(3000);
        assertEquals(2000,duration(out)); assertEquals(2,out.size());
    }
    @Test public void modeChangeCanReuseCheckpointWithoutSplittingUsage() {
        List<Span> out = new ArrayList<>(); UsageReducer r = reducer(out); r.event(1,"a",1000); r.advance(20000);
        UsageReducer after = new UsageReducer(r.json(), (p,s,e)->out.add(new Span(p,s,e))); after.advance(61000);
        assertEquals(60000,duration(out)); assertEquals(1000,after.activeSince);
    }
}
