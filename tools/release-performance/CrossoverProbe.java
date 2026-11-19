package dev.udak.diagnostic;

import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Method;
import java.lang.reflect.Proxy;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.util.Arrays;

/** Exclusive intervals measured against the same JDBC delegate for all three arms. */
public final class CrossoverProbe {
    public enum Metric {
        TOTAL, JDBC_PREPARE, JDBC_EXECUTE, JDBC_OTHER, HMAC, FINGERPRINT, EVENT_CREATE, EVENT_SINK,
        OBSERVE_PROXY, OTHER
    }

    public enum CacheOutcome { NONE, HIT, MISS }

    private static final Metric[] METRICS = Metric.values();
    private static final ThreadLocal<CrossoverProbe> ACTIVE = new ThreadLocal<>();

    private final long[] nanos = new long[METRICS.length];
    private final int[] calls = new int[METRICS.length];
    private CacheOutcome cacheOutcome;
    private boolean timing;
    private long timerStart;

    public void begin() {
        require(ACTIVE.get() == null && !timing);
        Arrays.fill(nanos, 0L);
        Arrays.fill(calls, 0);
        cacheOutcome = CacheOutcome.NONE;
        ACTIVE.set(this);
    }

    public static long start() {
        CrossoverProbe probe = ACTIVE.get();
        return probe == null ? 0 : probe.startInterval();
    }

    public static void finish(String metric, long started) {
        long stopped = System.nanoTime();
        CrossoverProbe probe = ACTIVE.get();
        if (probe != null) probe.record(Metric.valueOf(metric), started, stopped);
        else require(started == 0);
    }

    public static void recordCacheOutcome(boolean hit) {
        CrossoverProbe probe = ACTIVE.get();
        require(probe != null && !probe.timing && probe.cacheOutcome == CacheOutcome.NONE);
        probe.cacheOutcome = hit ? CacheOutcome.HIT : CacheOutcome.MISS;
    }

    private long startInterval() {
        require(!timing);
        timing = true;
        timerStart = System.nanoTime();
        return timerStart;
    }

    private void record(Metric metric, long started, long stopped) {
        long elapsed = stopped - started;
        require(timing && started == timerStart && elapsed >= 0);
        require(metric != Metric.TOTAL && metric != Metric.OTHER);
        timing = false;
        int index = metric.ordinal();
        nanos[index] = Math.addExact(nanos[index], elapsed);
        calls[index]++;
    }

    public CacheOutcome end(boolean observe, boolean first, long elapsed, long[][] samples, int index) {
        require(ACTIVE.get() == this && !timing && elapsed > 0);
        require(calls(Metric.JDBC_PREPARE) == 1 && calls(Metric.JDBC_EXECUTE) == 1);
        int events = observe ? 1 : 0;
        require(calls(Metric.HMAC) == events
                && calls(Metric.FINGERPRINT) == (observe && first ? 1 : 0)
                && calls(Metric.EVENT_CREATE) == events
                && calls(Metric.EVENT_SINK) == events);
        require(observe ? calls(Metric.OBSERVE_PROXY) > 0 : calls(Metric.OBSERVE_PROXY) == 0);
        CacheOutcome expected = observe ? (first ? CacheOutcome.MISS : CacheOutcome.HIT) : CacheOutcome.NONE;
        require(cacheOutcome == expected);

        long accounted = 0;
        for (long interval : nanos) accounted = Math.addExact(accounted, interval);
        require(accounted <= elapsed);
        nanos[Metric.TOTAL.ordinal()] = elapsed;
        nanos[Metric.OTHER.ordinal()] = elapsed - accounted;
        if (index >= 0) {
            for (Metric metric : METRICS) samples[metric.ordinal()][index] = nanos[metric.ordinal()];
        }
        return cacheOutcome;
    }

    private int calls(Metric metric) {
        return calls[metric.ordinal()];
    }

    public void clear() {
        require(ACTIVE.get() == this);
        ACTIVE.remove();
        timing = false;
    }

    public static Connection wrap(Connection connection) {
        return proxy(Connection.class, connection, null);
    }

    private static <T> T proxy(Class<T> type, T target, Connection sharedConnection) {
        return type.cast(Proxy.newProxyInstance(type.getClassLoader(), new Class<?>[] {type},
                (self, method, args) -> {
                    if (method.getDeclaringClass() == Object.class) {
                        return switch (method.getName()) {
                            case "equals" -> self == args[0];
                            case "hashCode" -> System.identityHashCode(self);
                            case "toString" -> "CrossoverJdbcProxy";
                            default -> throw new IllegalStateException("Unexpected JDBC proxy object method");
                        };
                    }
                    Connection connectionProxy = type == Connection.class ? (Connection) self : sharedConnection;
                    Object result = delegate(target, method, args);
                    if (result instanceof PreparedStatement statement) {
                        return proxy(PreparedStatement.class, statement, connectionProxy);
                    }
                    if (result instanceof ResultSet rows) return proxy(ResultSet.class, rows, connectionProxy);
                    if (result instanceof Connection connection) {
                        require(connection == target || target instanceof PreparedStatement);
                        return connectionProxy;
                    }
                    return result;
                }));
    }

    private static Object delegate(Object target, Method method, Object[] args) throws Throwable {
        try {
            CrossoverProbe probe = ACTIVE.get();
            if (probe == null) return method.invoke(target, args);
            Metric metric = switch (method.getName()) {
                case "prepareStatement" -> Metric.JDBC_PREPARE;
                case "executeQuery" -> Metric.JDBC_EXECUTE;
                default -> Metric.JDBC_OTHER;
            };
            long started = probe.startInterval();
            try {
                return method.invoke(target, args);
            } finally {
                probe.record(metric, started, System.nanoTime());
            }
        } catch (InvocationTargetException wrapped) {
            throw wrapped.getCause();
        }
    }

    private static void require(boolean valid) {
        if (!valid) throw new IllegalStateException("Crossover probe invariant failed");
    }
}
