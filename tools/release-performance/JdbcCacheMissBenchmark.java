package dev.udak.bench;

import dev.udak.observe.FingerprintStatus;
import dev.udak.observe.Framework;
import dev.udak.observe.ObservationPoint;
import dev.udak.observe.SqlObservation;
import dev.udak.observe.SqlObserver;
import dev.udak.observe.StatementKind;
import java.util.concurrent.TimeUnit;
import org.openjdk.jmh.annotations.Benchmark;
import org.openjdk.jmh.annotations.BenchmarkMode;
import org.openjdk.jmh.annotations.Mode;
import org.openjdk.jmh.annotations.OutputTimeUnit;
import org.openjdk.jmh.annotations.Scope;
import org.openjdk.jmh.annotations.Setup;
import org.openjdk.jmh.annotations.State;

@State(Scope.Thread)
@BenchmarkMode(Mode.AverageTime)
@OutputTimeUnit(TimeUnit.NANOSECONDS)
public class JdbcCacheMissBenchmark {
    private static final String FIRST_SQL = "select id, fixture_value from udak_perf_fixture_a where id = ?";
    private static final String SECOND_SQL = "select id, fixture_value from udak_perf_fixture_b where id = ?";

    private SqlObserver observer;
    private SqlObservation observed;
    private boolean useSecondSql;

    @Setup
    public void setup() {
        if (FIRST_SQL.length() != SECOND_SQL.length()
                || !FIRST_SQL.chars().allMatch(c -> c < 128)
                || !SECOND_SQL.chars().allMatch(c -> c < 128)) {
            throw new IllegalStateException("JDBC cache miss fixture inputs must be equal-length ASCII");
        }

        observer = new SqlObserver(event -> observed = event);
        observed = null;
        SqlObservation first = observe(FIRST_SQL);
        observed = null;
        if (!isNormalizedSelect(first) || observe(FIRST_SQL) != first) {
            throw new IllegalStateException("JDBC cache miss fixture failed to verify the first cache hit");
        }
        observed = null;
        SqlObservation second = observe(SECOND_SQL);
        observed = null;
        if (!isNormalizedSelect(second) || observe(SECOND_SQL) != second
                || first.fingerprintHash().equals(second.fingerprintHash())
                || first.queryIdHash().equals(second.queryIdHash())) {
            throw new IllegalStateException("JDBC cache miss fixture failed to verify distinct cache entries");
        }

        // The second shape is cached. Start with the first shape to force a miss on every call.
        useSecondSql = false;
        SqlObservation nextFirst = cacheMiss();
        SqlObservation nextSecond = cacheMiss();
        if (nextFirst == first || !first.equals(nextFirst)
                || nextSecond == second || !second.equals(nextSecond)) {
            throw new IllegalStateException("JDBC cache miss fixture failed to verify cache replacement");
        }
    }

    @Benchmark
    public SqlObservation cacheMiss() {
        String sql = useSecondSql ? SECOND_SQL : FIRST_SQL;
        useSecondSql = !useSecondSql;
        return observe(sql);
    }

    private SqlObservation observe(String sql) {
        observer.observe(Framework.JDBC, ObservationPoint.JDBC_EXECUTE, null, sql);
        return observed;
    }

    private static boolean isNormalizedSelect(SqlObservation event) {
        return event != null
                && event.framework() == Framework.JDBC
                && event.point() == ObservationPoint.JDBC_EXECUTE
                && event.statementKind() == StatementKind.SELECT
                && event.fingerprintStatus() == FingerprintStatus.NORMALIZED;
    }

    public static void main(String[] args) {
        new JdbcCacheMissBenchmark().setup();
        System.out.println("CACHE_MISS_PASS");
    }
}
