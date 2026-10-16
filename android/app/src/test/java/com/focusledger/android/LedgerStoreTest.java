package com.focusledger.android;

import org.junit.After;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RuntimeEnvironment;
import org.robolectric.annotation.Config;
import java.util.List;
import static org.junit.Assert.*;

@RunWith(org.robolectric.RobolectricTestRunner.class)
@Config(sdk = 30)
public class LedgerStoreTest {
    private LedgerStore store;
    private UsageReader reader;
    private static final long DAY = 1_790_000_000_000L;
    @Before public void open() { store = new LedgerStore(RuntimeEnvironment.getApplication()); reader = new UsageReader(RuntimeEnvironment.getApplication()); }
    @After public void close() { store.close(); }
    private void save(String scope, LedgerStore.Slice... slices) { store.commit(scope, null, List.of(slices), List.of(), reader); }
    private double total(String scope, long from, long to) { return store.ranking(scope, from, to).stream().mapToDouble(LedgerStore.Rank::seconds).sum(); }

    @Test public void withinDayTotals() {
        save("phone", new LedgerStore.Slice("reader", DAY + 8 * 3600000, DAY + 9 * 3600000),
            new LedgerStore.Slice("music", DAY + 9 * 3600000, DAY + 10 * 3600000),
            new LedgerStore.Slice("reader", DAY + 10 * 3600000, DAY + 10 * 3600000 + 1800000));
        List<LedgerStore.Rank> ranks = store.ranking("phone", DAY, DAY + 16 * 3600000);
        assertEquals(2, ranks.size()); assertEquals("reader", ranks.get(0).pkg());
        assertEquals(5400d, ranks.get(0).seconds(), 0d); assertEquals(3600d, ranks.get(1).seconds(), 0d);
        assertEquals(9000d, total("phone", DAY, DAY + 16 * 3600000), 0d);
    }
    @Test public void midnightClipping() {
        save("phone", new LedgerStore.Slice("reader", DAY - 1800000, DAY + 1800000));
        assertEquals(1800d, total("phone", DAY - 86400000, DAY), 0d);
        assertEquals(1800d, total("phone", DAY, DAY + 86400000), 0d);
    }
    @Test public void bothEdges() {
        save("phone", new LedgerStore.Slice("inside", DAY + 10000, DAY + 70000),
            new LedgerStore.Slice("before", DAY, DAY + 30000), new LedgerStore.Slice("after", DAY + 50000, DAY + 80000));
        List<LedgerStore.Rank> ranks = store.ranking("phone", DAY + 30000, DAY + 50000);
        assertEquals(1, ranks.size()); assertEquals("inside", ranks.get(0).pkg()); assertEquals(20d, ranks.get(0).seconds(), 0d);
    }
    @Test public void scopesAndReplay() {
        LedgerStore.Slice slice = new LedgerStore.Slice("reader", DAY + 10000, DAY + 70000);
        save("phone", slice); save("phone", slice); save("another-account", slice);
        assertEquals(60d, total("phone", DAY, DAY + 86400000), 0d);
        assertEquals(0d, total("unknown", DAY, DAY + 86400000), 0d);
    }
}
