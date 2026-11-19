import dev.udak.diagnostic.ExecuteIntervals;
import dev.udak.observe.FingerprintStatus;
import dev.udak.observe.Framework;
import dev.udak.observe.ObservationPoint;
import dev.udak.observe.ObservationSink;
import dev.udak.observe.SqlObservation;
import dev.udak.observe.SqlObserver;
import dev.udak.observe.StatementKind;
import dev.udak.observe.jdbc.ObserveDataSource;
import java.io.PrintStream;
import java.math.BigDecimal;
import java.math.RoundingMode;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Statement;
import java.util.StringJoiner;
import java.util.concurrent.TimeUnit;
import java.util.function.IntUnaryOperator;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import javax.sql.DataSource;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DelegatingDataSource;
import org.springframework.jdbc.datasource.SingleConnectionDataSource;

/** Correlates one JDBC execution with one PostgreSQL statistics delta on the owned connection. */
final class ExecuteTrial {
    private static final int WARMUP_PAIRS = 6;
    private static final int MEASURED_PAIRS = 32;
    private static final int PAIRS = WARMUP_PAIRS + MEASURED_PAIRS;
    private static final int TARGETS = PAIRS * 2;
    private static final int SNAPSHOTS = TARGETS + 1;
    private static final long SPACING_NS = TimeUnit.MILLISECONDS.toNanos(125);
    private static final long SECOND_NS = TimeUnit.SECONDS.toNanos(1);
    private static final Pattern QUERY_IDENTIFIER =
            Pattern.compile("(?m)^\\h*\"Query Identifier\"\\s*:\\s*(-?[0-9]{1,19})(?=\\s*[,}])");
    private static final String SNAPSHOT_SQL = """
            SELECT stats.calls, stats.plans, stats.total_plan_time, stats.total_exec_time,
                   pg_catalog.current_setting('compute_query_id') = 'on'
                   AND pg_catalog.current_setting('pg_stat_statements.track_planning') = 'on'
                   AND pg_catalog.current_setting('pg_stat_statements.track') = 'top'
                   AND pg_catalog.current_setting('pg_stat_statements.save') = 'off'
            FROM (VALUES (1)) AS baseline(marker)
            LEFT JOIN public.pg_stat_statements(false) AS stats
              ON stats.dbid = (SELECT oid FROM pg_catalog.pg_database WHERE datname = current_database())
             AND stats.userid = (SELECT oid FROM pg_catalog.pg_roles WHERE rolname = current_user)
             AND stats.toplevel
             AND stats.queryid = ?
            """;

    private enum Arm { PLAIN, CURRENT }

    private enum Metric {
        QUERY_WALL, JDBC_WALL, THREAD_CPU, READ_NS, WRITE_NS, READ_CALLS, WRITE_CALLS,
        READ_BYTES, WRITE_BYTES, SERVER_PLAN, SERVER_EXEC, SERVER_PLANS
    }

    private static final class EventCounter implements ObservationSink {
        private int count;
        private SqlObservation last;

        @Override
        public void accept(SqlObservation event) {
            count++;
            last = event;
        }
    }

    private record Stats(long calls, long plans, BigDecimal planningMs, BigDecimal executionMs) {
        private static final Stats EMPTY = new Stats(0, 0, BigDecimal.ZERO, BigDecimal.ZERO);

        Stats {
            require(calls >= 0 && plans >= 0 && planningMs != null && executionMs != null);
            require(planningMs.signum() >= 0 && executionMs.signum() >= 0);
        }

        ServerDelta since(Stats before) {
            long planCount = plans - before.plans;
            BigDecimal planning = planningMs.subtract(before.planningMs);
            BigDecimal execution = executionMs.subtract(before.executionMs);
            require(calls - before.calls == 1 && (planCount == 0 || planCount == 1));
            require(planning.signum() >= 0 && execution.signum() >= 0);
            require(planCount != 0 || planning.signum() == 0);
            return new ServerDelta(toNanos(planning), toNanos(execution), planCount);
        }

        private static long toNanos(BigDecimal millis) {
            return millis.movePointRight(6).setScale(0, RoundingMode.HALF_UP).longValueExact();
        }
    }

    private record ServerDelta(long planning, long execution, long plans) {}

    private final Connection connection;
    private final String sql;
    private final int rows;
    private final int timeoutSeconds;
    private final IntUnaryOperator valueFor;
    private final ExecuteIntervals intervals = new ExecuteIntervals();
    private final EventCounter events = new EventCounter();
    private final JdbcTemplate plain;
    private final JdbcTemplate current;
    private final long[][][] samples = new long[Arm.values().length][MEASURED_PAIRS][];
    private final int[] measuredOrders = new int[MEASURED_PAIRS];
    private final long[] starts = new long[TARGETS + SNAPSHOTS];
    private Stats lastStats;
    private SqlObservation firstEvent;
    private int requestsStarted;
    private int targetStarts;
    private int snapshotReads;
    private int verifiedRows;
    private int inFlight;
    private int maxInFlight;
    private long previousFinished;

    ExecuteTrial(Connection connection, String sql, int rows, int timeoutSeconds, IntUnaryOperator valueFor) {
        require(rows > 0 && timeoutSeconds > 0);
        this.connection = connection;
        this.sql = sql;
        this.rows = rows;
        this.timeoutSeconds = timeoutSeconds;
        this.valueFor = valueFor;
        // Both templates use the original logical release path on the same physical connection.
        DataSource shared = new DelegatingDataSource(new SingleConnectionDataSource(intervals.wrap(connection), true));
        plain = new JdbcTemplate(shared);
        current = new JdbcTemplate(new ObserveDataSource(shared, new SqlObserver(events)));
        plain.setQueryTimeout(timeoutSeconds);
        current.setQueryTimeout(timeoutSeconds);
    }

    void run() throws SQLException, InterruptedException {
        require(requestsStarted == 0 && connection.getAutoCommit());
        try (Statement ddl = connection.createStatement()) {
            ddl.setQueryTimeout(timeoutSeconds);
            ddl.executeUpdate("CREATE EXTENSION pg_stat_statements WITH SCHEMA public");
        }
        long queryId = identifyQuery();
        try (PreparedStatement snapshot = connection.prepareStatement(SNAPSHOT_SQL)) {
            snapshot.setQueryTimeout(timeoutSeconds);
            snapshot.setLong(1, queryId);
            lastStats = readSnapshot(snapshot, true);
            require(lastStats.calls() == 0);
            for (int pair = 0; pair < PAIRS; pair++) {
                int id = 1 + pair % rows;
                int index = pair - WARMUP_PAIRS;
                int order = pair % 2;
                Arm first = order == 0 ? Arm.PLAIN : Arm.CURRENT;
                Arm second = order == 0 ? Arm.CURRENT : Arm.PLAIN;
                sample(first, id, index, snapshot);
                sample(second, id, index, snapshot);
                if (index >= 0) measuredOrders[index] = order;
            }
        }
    }

    private long identifyQuery() throws SQLException {
        try (PreparedStatement explain = connection.prepareStatement(
                "EXPLAIN (VERBOSE, COSTS OFF, FORMAT JSON) " + sql)) {
            explain.setQueryTimeout(timeoutSeconds);
            explain.setInt(1, 1);
            try (ResultSet result = explain.executeQuery()) {
                require(result.next());
                String plan = result.getString(1);
                require(plan != null && plan.length() <= 16_384 && !result.next());
                Matcher identifiers = QUERY_IDENTIFIER.matcher(plan);
                require(identifiers.find());
                long id = Long.parseLong(identifiers.group(1));
                require(id != 0 && !identifiers.find());
                return id;
            }
        }
    }

    private Stats readSnapshot(PreparedStatement snapshot, boolean initial) throws SQLException, InterruptedException {
        pace();
        snapshotReads++;
        startRequest();
        try (ResultSet result = snapshot.executeQuery()) {
            require(result.next() && result.getBoolean(5));
            long calls = result.getLong(1);
            if (result.wasNull()) {
                require(initial && !result.next());
                return Stats.EMPTY;
            }
            long plans = result.getLong(2);
            require(!result.wasNull());
            Stats stats = new Stats(calls, plans, result.getBigDecimal(3), result.getBigDecimal(4));
            require(!result.next());
            return stats;
        } finally {
            finishRequest();
        }
    }

    private void sample(Arm arm, int id, int index, PreparedStatement snapshot) throws SQLException, InterruptedException {
        int previousEvents = events.count;
        JdbcTemplate template = arm == Arm.PLAIN ? plain : current;
        pace();
        intervals.begin();
        targetStarts++;
        long queryWall;
        ExecuteIntervals.Sample sample;
        long started = startRequest();
        try {
            template.query(sql, statement -> statement.setInt(1, id), result -> {
                require(result.next() && result.getInt(1) == id && result.getInt(2) == valueFor.applyAsInt(id));
                require(!result.next());
                return Boolean.TRUE;
            });
            queryWall = System.nanoTime() - started;
            sample = intervals.finish();
        } finally {
            intervals.cancel();
            finishRequest();
        }
        verifiedRows++;
        require(queryWall >= sample.jdbcWall() && sample.jdbcWall() > 0 && sample.threadCpu() >= 0);
        require(sample.readNs() >= 0 && sample.writeNs() >= 0 && sample.readNs() <= sample.jdbcWall() - sample.writeNs());
        require(sample.readCalls() > 0 && sample.writeCalls() > 0 && sample.readBytes() > 0 && sample.writeBytes() > 0);
        require(events.count == previousEvents + (arm == Arm.CURRENT ? 1 : 0));
        if (arm == Arm.CURRENT) verifyEvent(events.last);

        Stats stats = readSnapshot(snapshot, false);
        ServerDelta server = stats.since(lastStats);
        lastStats = stats;
        if (index >= 0) {
            samples[arm.ordinal()][index] = new long[] {
                    queryWall, sample.jdbcWall(), sample.threadCpu(), sample.readNs(), sample.writeNs(),
                    sample.readCalls(), sample.writeCalls(), sample.readBytes(), sample.writeBytes(),
                    server.planning(), server.execution(), server.plans()
            };
        }
    }

    private void pace() throws InterruptedException {
        if (requestsStarted == 0) return;
        long remaining;
        // Spacing from completion also covers the later physical execute inside JdbcTemplate.
        while ((remaining = SPACING_NS - (System.nanoTime() - previousFinished)) > 0) {
            TimeUnit.NANOSECONDS.sleep(remaining);
        }
    }

    private long startRequest() {
        require(inFlight == 0 && requestsStarted < starts.length);
        maxInFlight = Math.max(maxInFlight, ++inFlight);
        long started = System.nanoTime();
        starts[requestsStarted++] = started;
        return started;
    }

    private void finishRequest() {
        require(inFlight == 1);
        inFlight--;
        previousFinished = System.nanoTime();
    }

    private void verifyEvent(SqlObservation event) {
        require(event.framework() == Framework.JDBC && event.point() == ObservationPoint.JDBC_EXECUTE);
        require(event.statementKind() == StatementKind.SELECT && event.fingerprintStatus() == FingerprintStatus.NORMALIZED);
        if (firstEvent == null) firstEvent = event;
        require(firstEvent.equals(event));
    }

    void report(PrintStream report) {
        require(targetStarts == TARGETS && snapshotReads == SNAPSHOTS && requestsStarted == starts.length);
        require(verifiedRows == TARGETS && events.count == PAIRS && inFlight == 0 && maxInFlight == 1);
        int maxRolling = 0;
        long minSpacing = Long.MAX_VALUE;
        int left = 0;
        for (int i = 0; i < requestsStarted; i++) {
            while (starts[i] - starts[left] >= SECOND_NS) left++;
            maxRolling = Math.max(maxRolling, i - left + 1);
            if (i > 0) minSpacing = Math.min(minSpacing, starts[i] - starts[i - 1]);
        }
        require(minSpacing >= SPACING_NS && maxRolling <= 8);

        report.println("PG_EXECUTE_DETAIL target_starts=" + targetStarts + " snapshot_reads=" + snapshotReads
                + " warmup_pairs=" + WARMUP_PAIRS + " measured_pairs=" + MEASURED_PAIRS
                + " verified_rows=" + verifiedRows + " events=" + events.count + " errors=0 max_in_flight=" + maxInFlight
                + " max_rolling_second=" + maxRolling + " min_spacing_ns=" + minSpacing);
        StringJoiner orders = new StringJoiner(",");
        for (int order : measuredOrders) orders.add(Integer.toString(order));
        report.println("PG_EXECUTE_ORDERS " + orders);
        for (Arm arm : Arm.values()) {
            for (Metric metric : Metric.values()) {
                StringJoiner values = new StringJoiner(",");
                for (long[] point : samples[arm.ordinal()]) values.add(Long.toString(point[metric.ordinal()]));
                report.println("PG_EXECUTE " + arm + " " + metric + " " + values);
            }
        }
    }

    private static void require(boolean valid) {
        if (!valid) throw new IllegalStateException("PostgreSQL execute trial invariant failed");
    }
}
