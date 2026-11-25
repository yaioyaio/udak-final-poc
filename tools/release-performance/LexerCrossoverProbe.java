package dev.udak.diagnostic;

import com.sun.management.ThreadMXBean;
import dev.udak.observe.FingerprintStatus;
import dev.udak.observe.Framework;
import dev.udak.observe.ObservationPoint;
import dev.udak.observe.SqlObservation;
import dev.udak.observe.SqlObserver;
import java.lang.management.ManagementFactory;
import java.lang.reflect.Proxy;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.ArrayList;
import java.util.function.LongSupplier;

/** Diagnostic-only, single-threaded measurement for one fixed SELECT. */
public final class LexerCrossoverProbe {
    private static Thread owner;
    private static LongSupplier allocatedBytes;
    private static boolean active;
    private static boolean after;
    private static long allocationStart;
    private static long allocation;
    private static long jdbc;

    private LexerCrossoverProbe() {}

    public static void initialize() {
        var bean = ManagementFactory.getThreadMXBean();
        require(bean instanceof ThreadMXBean);
        var allocationBean = (ThreadMXBean) bean;
        require(allocationBean.isThreadAllocatedMemorySupported());
        if (!allocationBean.isThreadAllocatedMemoryEnabled()) {
            allocationBean.setThreadAllocatedMemoryEnabled(true);
        }
        owner = Thread.currentThread();
        allocatedBytes = allocationBean::getCurrentThreadAllocatedBytes;
        require(allocatedBytes.getAsLong() >= 0);
    }

    public static void begin(boolean candidate) {
        require(owner == Thread.currentThread() && !active);
        active = true;
        after = candidate;
        allocationStart = allocation = jdbc = -1;
    }

    public static boolean useCandidate() {
        require(active && owner == Thread.currentThread());
        return after;
    }

    public static void startNormalization() {
        require(active && owner == Thread.currentThread() && allocationStart == -1);
        allocationStart = allocatedBytes.getAsLong();
        require(allocationStart >= 0);
    }

    public static void finishNormalization() {
        require(active && owner == Thread.currentThread() && allocationStart >= 0 && allocation == -1);
        long finished = allocatedBytes.getAsLong();
        require(finished >= allocationStart);
        allocation = finished - allocationStart;
    }

    public static ResultSet execute(PreparedStatement statement) throws SQLException {
        require(active && owner == Thread.currentThread() && allocation >= 0 && jdbc == -1);
        long started = System.nanoTime();
        try {
            return statement.executeQuery();
        } finally {
            jdbc = System.nanoTime() - started;
        }
    }

    public static Sample end(long totalNanos) {
        require(active && owner == Thread.currentThread() && allocation >= 0 && jdbc >= 0 && jdbc <= totalNanos);
        active = false;
        return new Sample(allocation, jdbc);
    }

    public record Sample(long shapeAllocatedBytes, long jdbcExecuteNanos) {}

    public static void main(String[] args) throws SQLException {
        require(args.length == 0);
        initialize();
        var jvmCounter = allocatedBytes;
        var fixture = (PreparedStatement) Proxy.newProxyInstance(LexerCrossoverProbe.class.getClassLoader(),
                new Class<?>[] {PreparedStatement.class}, (proxy, method, parameters) -> {
                    require(method.getName().equals("executeQuery"));
                    return null;
                });
        allocatedBytes = () -> 18;
        begin(false);
        require(!useCandidate());
        rejects(() -> end(Long.MAX_VALUE));
        startNormalization();
        rejects(LexerCrossoverProbe::startNormalization);
        allocatedBytes = () -> 17;
        rejects(LexerCrossoverProbe::finishNormalization);
        allocatedBytes = () -> 18;
        finishNormalization();
        rejects(LexerCrossoverProbe::finishNormalization);
        require(execute(fixture) == null);
        require(end(Long.MAX_VALUE).shapeAllocatedBytes() == 0);
        allocatedBytes = jvmCounter;
        var events = new ArrayList<SqlObservation>(2);
        var observer = new SqlObserver(events::add);
        for (int index = 0; index < 2; index++) {
            begin(index == 1);
            require(useCandidate() == (index == 1));
            observer.observe(Framework.JDBC, ObservationPoint.JDBC_EXECUTE, null,
                    "SELECT id, fixture_value FROM udak_perf_fixture WHERE id = ?");
            require(events.size() == index + 1);
            require(execute(fixture) == null);
            var sample = end(Long.MAX_VALUE);
            require(sample.shapeAllocatedBytes() >= 0 && sample.jdbcExecuteNanos() >= 0);
        }
        require(events.get(0).fingerprintStatus() == FingerprintStatus.NORMALIZED);
        require(events.get(0).equals(events.get(1)));
        System.out.println("LEXER_CROSSOVER_PROBE PASS");
    }

    private static void rejects(Runnable operation) {
        try {
            operation.run();
            throw new AssertionError();
        } catch (IllegalStateException expected) {
            // The invalid transition must stay outside the measurement.
        }
    }

    private static void require(boolean condition) {
        if (!condition) throw new IllegalStateException("Lexer crossover invariant failed");
    }
}
