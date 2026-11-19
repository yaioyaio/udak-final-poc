import dev.udak.diagnostic.CrossoverProbe;
import dev.udak.diagnostic.CrossoverProbe.CacheOutcome;
import dev.udak.diagnostic.CrossoverProbe.Metric;
import dev.udak.observe.FingerprintStatus;
import dev.udak.observe.Framework;
import dev.udak.observe.ObservationPoint;
import dev.udak.observe.ObservationSink;
import dev.udak.observe.PriorSqlObserver;
import dev.udak.observe.SqlObservation;
import dev.udak.observe.SqlObserver;
import dev.udak.observe.StatementKind;
import dev.udak.observe.jdbc.ObserveDataSource;
import dev.udak.observe.jdbc.PriorObserveDataSource;
import java.io.PrintStream;
import java.sql.Connection;
import java.util.SplittableRandom;
import java.util.StringJoiner;
import java.util.concurrent.TimeUnit;
import java.util.function.IntUnaryOperator;
import javax.sql.DataSource;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DelegatingDataSource;
import org.springframework.jdbc.datasource.SingleConnectionDataSource;

/** Bounded JdbcTemplate SELECTs with three arms sharing one close-suppressed connection. */
final class CrossoverTrial {
    private static final int WARMUP_TRIPLETS = 8;
    private static final int MEASURED_TRIPLETS = 60;
    private static final int TOTAL_TRIPLETS = WARMUP_TRIPLETS + MEASURED_TRIPLETS;
    private static final long INTERVAL_NS = TimeUnit.MILLISECONDS.toNanos(125);
    private static final long SECOND_NS = TimeUnit.SECONDS.toNanos(1);
    private static final long ORDER_SEED = 87453L;

    private enum Arm { PLAIN, PRIOR, CURRENT }

    private static final Arm[] ARMS = Arm.values();
    private static final Metric[] METRICS = Metric.values();
    // Permutation indices follow the lexicographic order of the arm labels above.
    private static final Arm[][] ORDERS = {
        {Arm.PLAIN, Arm.PRIOR, Arm.CURRENT},
        {Arm.PLAIN, Arm.CURRENT, Arm.PRIOR},
        {Arm.PRIOR, Arm.PLAIN, Arm.CURRENT},
        {Arm.PRIOR, Arm.CURRENT, Arm.PLAIN},
        {Arm.CURRENT, Arm.PLAIN, Arm.PRIOR},
        {Arm.CURRENT, Arm.PRIOR, Arm.PLAIN}
    };

    private static final class EventCounter implements ObservationSink {
        private int count;
        private SqlObservation last;

        @Override
        public void accept(SqlObservation event) {
            count++;
            last = event;
        }
    }

    private final String sql;
    private final int rows;
    private final IntUnaryOperator valueFor;
    private final CrossoverProbe probe = new CrossoverProbe();
    private final EventCounter priorEvents = new EventCounter();
    private final EventCounter currentEvents = new EventCounter();
    private final JdbcTemplate[] templates = new JdbcTemplate[ARMS.length];
    private final long[][][] samples = new long[ARMS.length][METRICS.length][MEASURED_TRIPLETS];
    private final int[] cacheHits = new int[ARMS.length];
    private final int[] cacheMisses = new int[ARMS.length];
    private final int[] measuredOrders = new int[MEASURED_TRIPLETS];
    private final long[] starts = new long[TOTAL_TRIPLETS * ARMS.length];
    private SqlObservation firstEvent;
    private int started;
    private int completed;
    private int verifiedRows;
    private int inFlight;
    private int maxInFlight;

    CrossoverTrial(Connection connection, String sql, int rows, int timeoutSeconds, IntUnaryOperator valueFor) {
        require(rows > 0 && timeoutSeconds > 0);
        this.sql = sql;
        this.rows = rows;
        this.valueFor = valueFor;
        // The ordinary DataSource release path applies to every template.
        DataSource shared = new DelegatingDataSource(new SingleConnectionDataSource(CrossoverProbe.wrap(connection), true));
        templates[Arm.PLAIN.ordinal()] = new JdbcTemplate(shared);
        templates[Arm.PRIOR.ordinal()] = new JdbcTemplate(
                new PriorObserveDataSource(shared, new PriorSqlObserver(priorEvents)));
        templates[Arm.CURRENT.ordinal()] = new JdbcTemplate(
                new ObserveDataSource(shared, new SqlObserver(currentEvents)));
        for (JdbcTemplate template : templates) template.setQueryTimeout(timeoutSeconds);
    }

    void run() throws InterruptedException {
        require(started == 0);
        for (int triplet = 0; triplet < WARMUP_TRIPLETS; triplet++) {
            runTriplet(triplet, triplet % ORDERS.length);
        }
        SplittableRandom random = new SplittableRandom(ORDER_SEED);
        for (int blockStart = 0; blockStart < MEASURED_TRIPLETS; blockStart += ORDERS.length) {
            int[] block = shuffledOrders(random);
            for (int i = 0; i < block.length; i++) {
                int index = blockStart + i;
                runTriplet(WARMUP_TRIPLETS + index, block[i]);
                measuredOrders[index] = block[i];
            }
        }
    }

    private static int[] shuffledOrders(SplittableRandom random) {
        int[] block = {0, 1, 2, 3, 4, 5};
        for (int i = block.length - 1; i > 0; i--) {
            int other = random.nextInt(i + 1);
            int order = block[i];
            block[i] = block[other];
            block[other] = order;
        }
        return block;
    }

    private void runTriplet(int triplet, int order) throws InterruptedException {
        int id = 1 + triplet % rows;
        for (Arm arm : ORDERS[order]) sample(arm, id, triplet);
    }

    private void sample(Arm arm, int id, int triplet) throws InterruptedException {
        int priorCount = priorEvents.count;
        int currentCount = currentEvents.count;
        pace();

        require(inFlight == 0 && started < starts.length);
        probe.begin();
        maxInFlight = Math.max(maxInFlight, ++inFlight);
        int startIndex = started++;
        int armIndex = arm.ordinal();
        JdbcTemplate template = templates[armIndex];
        try {
            long start = System.nanoTime();
            template.query(sql, statement -> statement.setInt(1, id), result -> {
                require(result.next() && result.getInt(1) == id && result.getInt(2) == valueFor.applyAsInt(id));
                require(!result.next());
                return Boolean.TRUE;
            });
            long elapsed = System.nanoTime() - start;
            starts[startIndex] = start;
            CacheOutcome outcome = probe.end(arm != Arm.PLAIN, triplet == 0,
                    elapsed, samples[armIndex], triplet - WARMUP_TRIPLETS);
            if (outcome == CacheOutcome.HIT) cacheHits[armIndex]++;
            if (outcome == CacheOutcome.MISS) cacheMisses[armIndex]++;
        } finally {
            probe.clear();
            inFlight--;
        }
        verifiedRows++;

        require(priorEvents.count == priorCount + (arm == Arm.PRIOR ? 1 : 0)
                && currentEvents.count == currentCount + (arm == Arm.CURRENT ? 1 : 0));
        if (arm == Arm.PRIOR) verifyEvent(priorEvents.last);
        if (arm == Arm.CURRENT) verifyEvent(currentEvents.last);
        completed++;
    }

    private void pace() throws InterruptedException {
        if (started == 0) return;
        long remaining;
        while ((remaining = INTERVAL_NS - (System.nanoTime() - starts[started - 1])) > 0) {
            TimeUnit.NANOSECONDS.sleep(remaining);
        }
    }

    private void verifyEvent(SqlObservation event) {
        require(event.framework() == Framework.JDBC && event.point() == ObservationPoint.JDBC_EXECUTE
                && event.statementKind() == StatementKind.SELECT && event.fingerprintStatus() == FingerprintStatus.NORMALIZED);
        if (firstEvent == null) firstEvent = event;
        require(firstEvent.equals(event));
    }

    void report(PrintStream report) {
        require(started == starts.length && completed == started && verifiedRows == completed && inFlight == 0);
        require(priorEvents.count == TOTAL_TRIPLETS && currentEvents.count == TOTAL_TRIPLETS && maxInFlight == 1);
        require(cacheHits[Arm.PRIOR.ordinal()] == TOTAL_TRIPLETS - 1 && cacheMisses[Arm.PRIOR.ordinal()] == 1
                && cacheHits[Arm.CURRENT.ordinal()] == TOTAL_TRIPLETS - 1 && cacheMisses[Arm.CURRENT.ordinal()] == 1);
        int maxRolling = 0;
        long minSpacing = Long.MAX_VALUE;
        int left = 0;
        for (int i = 0; i < started; i++) {
            while (starts[i] - starts[left] >= SECOND_NS) left++;
            maxRolling = Math.max(maxRolling, i - left + 1);
            if (i > 0) minSpacing = Math.min(minSpacing, starts[i] - starts[i - 1]);
        }
        require(minSpacing >= INTERVAL_NS && maxRolling <= 8);

        report.println("POSTGRES_CROSSOVER starts=" + started + " completed=" + completed
                + " warmup_triplets=" + WARMUP_TRIPLETS + " measured_triplets=" + MEASURED_TRIPLETS
                + " verified_rows=" + verifiedRows + " prior_events=" + priorEvents.count
                + " current_events=" + currentEvents.count + " errors=0 max_in_flight=" + maxInFlight
                + " max_rolling_second=" + maxRolling + " min_spacing_ns=" + minSpacing);
        StringJoiner orders = new StringJoiner(",");
        for (int order : measuredOrders) orders.add(Integer.toString(order));
        report.println("CROSSOVER_ORDERS " + orders);
        for (Arm arm : ARMS) {
            for (Metric metric : METRICS) {
                StringJoiner values = new StringJoiner(",");
                for (long elapsed : samples[arm.ordinal()][metric.ordinal()]) values.add(Long.toString(elapsed));
                report.println("CROSSOVER " + arm + " " + metric + " " + values);
            }
        }
        reportCache(report, Arm.PRIOR);
        reportCache(report, Arm.CURRENT);
    }

    private void reportCache(PrintStream report, Arm arm) {
        report.println("CROSSOVER_CACHE " + arm + " hits=" + cacheHits[arm.ordinal()]
                + " misses=" + cacheMisses[arm.ordinal()]);
    }

    private static void require(boolean valid) {
        if (!valid) throw new IllegalStateException("Crossover trial invariant failed");
    }
}
