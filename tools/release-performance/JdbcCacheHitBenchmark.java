package dev.udak.bench;

import dev.udak.observe.SqlObserver;
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
public class JdbcCacheHitBenchmark {
    private static final String SQL = "select id, fixture_value from udak_perf_fixture where id = ?";
    private SqlObserver observer;

    @Setup
    public void setup() {
        observer = new SqlObserver(event -> {});
        SqlObserver.PreparedObservation initial = observer.prepareJdbc(SQL);
        if (initial == null || initial != observer.prepareJdbc(SQL)) {
            throw new IllegalStateException("JDBC cache hit fixture unavailable");
        }
    }

    @Benchmark
    public SqlObserver.PreparedObservation cacheHit() {
        return observer.prepareJdbc(SQL);
    }

    public static void main(String[] args) {
        JdbcCacheHitBenchmark fixture = new JdbcCacheHitBenchmark();
        fixture.setup();
        if (fixture.cacheHit() == null) {
            throw new IllegalStateException("JDBC cache hit fixture failed");
        }
        System.out.println("CACHE_HIT_PASS");
    }
}
