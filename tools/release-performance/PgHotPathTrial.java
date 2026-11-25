package dev.udak.diagnostic;

import dev.udak.observe.Framework;
import dev.udak.observe.ObservationPoint;
import dev.udak.observe.ObservationSink;
import dev.udak.observe.PreviousSqlObserver;
import dev.udak.observe.SqlObservation;
import dev.udak.observe.SqlObserver;
import dev.udak.observe.UnavailableReason;
import dev.udak.observe.jdbc.ObserveDataSource;
import dev.udak.observe.jdbc.PreviousObserveDataSource;
import java.io.PrintStream;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.Arrays;
import java.util.StringJoiner;
import java.util.concurrent.TimeUnit;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.PreparedStatementCallback;
import org.springframework.jdbc.datasource.DelegatingDataSource;
import org.springframework.jdbc.datasource.SingleConnectionDataSource;

/** A single-threaded diagnostic using two baseline labels and two pinned Observe implementations. */
public final class PgHotPathTrial {
    private static final int[][] ORDERS = {{0,1,3,2}, {1,2,0,3}, {2,3,1,0}, {3,0,2,1}};
    private static final String[] ARMS = {"PLAIN_A", "PLAIN_B", "BEFORE", "AFTER"};
    private static final int GROUPS = 32;
    private static final long INTERVAL_NS = 125_000_000L;
    private static final String SELECT = "SELECT id, fixture_value FROM udak_perf_fixture WHERE id = ?";

    public enum Metric { TOTAL, CONNECTION_WRAP, STATEMENT_WRAP, METADATA, EVENT_SINK, JDBC_PREPARE, JDBC_EXECUTE }
    private static final Metric[] METRICS = Metric.values();
    private static final long[] intervals = new long[METRICS.length];
    private static final int[] calls = new int[METRICS.length];
    private static boolean active;
    private static boolean timing;
    private static long timerStart;

    private final JdbcTemplate[] templates;
    private final long[][][] samples = new long[ARMS.length][METRICS.length][GROUPS];
    private final long[] starts = new long[160];
    private final StringJoiner schedule = new StringJoiner(",");
    private SqlObservation firstEvent;
    private int events;
    private int completed;

    public PgHotPathTrial(Connection connection) {
        var shared = new DelegatingDataSource(new SingleConnectionDataSource(connection, true));
        JdbcTemplate plain = new JdbcTemplate(shared);
        ObservationSink sink = new ObservationSink() {
            public void accept(SqlObservation event) {
                throw new AssertionError();
            }

            public void accept(SqlObservation event, UnavailableReason reason) {
                require(reason == UnavailableReason.NONE && event.framework() == Framework.JDBC
                        && event.point() == ObservationPoint.JDBC_EXECUTE);
                if (firstEvent == null) firstEvent = event;
                require(firstEvent.equals(event));
                events++;
            }
        };
        JdbcTemplate before = new JdbcTemplate(new PreviousObserveDataSource(shared, new PreviousSqlObserver(sink)));
        JdbcTemplate after = new JdbcTemplate(new ObserveDataSource(shared, new SqlObserver(sink)));
        templates = new JdbcTemplate[] {plain, plain, before, after};
        for (JdbcTemplate template : templates) template.setQueryTimeout(3);
    }

    public void run() throws InterruptedException {
        for (int block = 0; block < 4; block++) {
            for (int slot = 0; slot < 10; slot++) {
                int row = 1 + (slot + 2 * block) % 8;
                int group = slot < 2 ? -1 : block * 8 + slot - 2;
                for (int arm : ORDERS[(row - 1 + block) % ORDERS.length]) {
                    if (completed > 0) {
                        long wait;
                        while ((wait = INTERVAL_NS - (System.nanoTime() - starts[completed - 1])) > 0) {
                            TimeUnit.NANOSECONDS.sleep(wait);
                        }
                    }
                    starts[completed++] = sample(arm, row, group);
                    schedule.add(Integer.toString(4 * row + arm));
                }
            }
        }
    }

    private long sample(int arm, int row, int group) {
        require(!active && !timing);
        Arrays.fill(intervals, 0);
        Arrays.fill(calls, 0);
        int expected = arm < 2 ? 0 : 1;
        int eventsBefore = events;
        active = true;
        long start = System.nanoTime();
        try {
            templates[arm].execute(connection -> arm < 2 ? prepare(connection, SELECT)
                    : connection.prepareStatement(SELECT), (PreparedStatementCallback<Boolean>) statement -> {
                statement.setInt(1, row);
                try (ResultSet rows = arm < 2 ? execute(statement) : statement.executeQuery()) {
                    require(rows.next() && rows.getInt(1) == row && rows.getInt(2) == 100 + 7 * row);
                    require(!rows.next());
                }
                return true;
            });
        } finally {
            active = false;
        }
        long elapsed = System.nanoTime() - start;
        require(!timing && elapsed > 0 && events == eventsBefore + expected);
        long accounted = 0;
        for (Metric metric : METRICS) {
            if (metric == Metric.TOTAL) continue;
            int i = metric.ordinal();
            require(calls[i] == (metric == Metric.JDBC_PREPARE || metric == Metric.JDBC_EXECUTE ? 1 : expected));
            accounted = Math.addExact(accounted, intervals[i]);
        }
        require(accounted <= elapsed);
        intervals[Metric.TOTAL.ordinal()] = elapsed;
        if (group >= 0) {
            for (int i = 0; i < METRICS.length; i++) samples[arm][i][group] = intervals[i];
        }
        return start;
    }

    public static long start() {
        require(active && !timing);
        timing = true;
        timerStart = System.nanoTime();
        return timerStart;
    }

    public static void finish(Metric metric, long start) {
        long elapsed = System.nanoTime() - start;
        require(active && timing && start == timerStart && elapsed >= 0);
        timing = false;
        intervals[metric.ordinal()] += elapsed;
        calls[metric.ordinal()]++;
    }

    public static ResultSet execute(PreparedStatement statement) throws SQLException {
        long start = start();
        try {
            return statement.executeQuery();
        } finally {
            finish(Metric.JDBC_EXECUTE, start);
        }
    }

    public static PreparedStatement prepare(Connection connection, String sql) throws SQLException {
        long start = start();
        try {
            return connection.prepareStatement(sql);
        } finally {
            finish(Metric.JDBC_PREPARE, start);
        }
    }

    public void report(PrintStream out) {
        require(completed == starts.length && events == 80 && firstEvent != null);
        out.println("PG_HOTPATH starts=160 rows=160 events=80 groups=32");
        out.println("EVENT_KEY " + firstEvent.queryIdHash() + " " + firstEvent.fingerprintHash());
        out.println("SCHEDULE " + schedule);
        long[] gaps = new long[starts.length - 1];
        for (int i = 1; i < starts.length; i++) gaps[i - 1] = starts[i] - starts[i - 1];
        reportSeries(out, "GAPS_NS", gaps);
        for (int arm = 0; arm < ARMS.length; arm++) {
            for (Metric metric : METRICS) {
                reportSeries(out, "SAMPLE " + ARMS[arm] + " " + metric, samples[arm][metric.ordinal()]);
            }
        }
    }

    private static void reportSeries(PrintStream out, String label, long[] values) {
        StringJoiner series = new StringJoiner(",");
        for (long value : values) series.add(Long.toString(value));
        out.println(label + " " + series);
    }

    public static void main(String[] args) throws SQLException {
        require(args.length == 0);
        try (Connection connection = DriverManager.getConnection("jdbc:h2:mem:udak_hotpath_contract")) {
            try (var statement = connection.createStatement()) {
                statement.executeUpdate("CREATE TABLE udak_perf_fixture (id INTEGER PRIMARY KEY, fixture_value INTEGER NOT NULL)");
                statement.executeUpdate("INSERT INTO udak_perf_fixture VALUES (1, 107)");
            }
            var trial = new PgHotPathTrial(connection);
            for (int arm : ORDERS[0]) trial.sample(arm, 1, 0);
            require(trial.events == 2 && trial.firstEvent != null);
        }
        System.out.println("PG_HOTPATH_CONTRACT PASS");
    }

    private static void require(boolean condition) {
        if (!condition) throw new IllegalStateException("PostgreSQL diagnostic invariant failed");
    }
}
