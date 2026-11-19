package dev.udak.diagnostic;

import java.io.PrintStream;
import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Method;
import java.lang.reflect.Proxy;
import java.sql.CallableStatement;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.Statement;
import java.util.Arrays;
import java.util.StringJoiner;

/** Exclusive wall-clock intervals for one single-threaded, fixed-size diagnostic trial. */
public final class AttributionProbe {
    private static final int WARMUP = 8;
    private static final int MEASURED = 96;

    private enum Metric {
        TOTAL, JDBC_PREPARE, JDBC_EXECUTE, JDBC_OTHER, FINGERPRINT, EVENT_CREATE, EVENT_SINK,
        OBSERVE_PROXY, OTHER
    }

    private static final Metric[] METRICS = Metric.values();
    private static final class Arm {
        final long[][] samples = new long[METRICS.length][MEASURED];
        int completed;
    }

    private static final Arm PLAIN = new Arm();
    private static final Arm OBSERVE = new Arm();
    private static final long[] nanos = new long[METRICS.length];
    private static final int[] calls = new int[METRICS.length];
    private static Arm active;
    private static boolean timing;
    private static long timerStart;

    private AttributionProbe() {}

    public static void begin(boolean observe) {
        require(active == null && !timing);
        Arm arm = observe ? OBSERVE : PLAIN;
        require(arm.completed < WARMUP + MEASURED);
        Arrays.fill(nanos, 0L);
        Arrays.fill(calls, 0);
        active = arm;
    }

    public static long start() {
        require(active != null && !timing);
        timing = true;
        timerStart = System.nanoTime();
        return timerStart;
    }

    public static void finish(String metric, long started) {
        long stopped = System.nanoTime();
        record(Metric.valueOf(metric), started, stopped);
    }

    private static void record(Metric metric, long started, long stopped) {
        long elapsed = stopped - started;
        require(timing && started == timerStart && elapsed >= 0);
        timing = false;
        int index = metric.ordinal();
        nanos[index] = Math.addExact(nanos[index], elapsed);
        calls[index]++;
    }

    public static Connection wrap(Connection raw) {
        return proxy(Connection.class, raw);
    }

    private static <T> T proxy(Class<T> type, T target) {
        return type.cast(Proxy.newProxyInstance(type.getClassLoader(), new Class<?>[] {type},
                (self, method, args) -> {
                    if (method.getDeclaringClass() == Object.class) {
                        return switch (method.getName()) {
                            case "equals" -> self == args[0];
                            case "hashCode" -> System.identityHashCode(self);
                            case "toString" -> "DiagnosticJdbcProxy";
                            default -> throw new AssertionError();
                        };
                    }
                    Object result = delegate(target, method, args);
                    if (result instanceof CallableStatement statement) return proxy(CallableStatement.class, statement);
                    if (result instanceof PreparedStatement statement) return proxy(PreparedStatement.class, statement);
                    if (result instanceof Statement statement) return proxy(Statement.class, statement);
                    if (result instanceof ResultSet rows) return proxy(ResultSet.class, rows);
                    if (result instanceof Connection connection) return wrap(connection);
                    return result;
                }));
    }

    private static Object delegate(Object target, Method method, Object[] args) throws Throwable {
        try {
            if (active == null) return method.invoke(target, args);
            Metric metric = switch (method.getName()) {
                case "prepareStatement" -> Metric.JDBC_PREPARE;
                case "executeQuery" -> Metric.JDBC_EXECUTE;
                default -> Metric.JDBC_OTHER;
            };
            long started = start();
            try {
                return method.invoke(target, args);
            } finally {
                record(metric, started, System.nanoTime());
            }
        } catch (InvocationTargetException wrapped) {
            throw wrapped.getCause();
        }
    }

    public static void end(boolean observe, int measuredIndex, long elapsed) {
        Arm arm = observe ? OBSERVE : PLAIN;
        require(active == arm && !timing && measuredIndex == arm.completed - WARMUP && elapsed > 0);
        require(calls[Metric.JDBC_PREPARE.ordinal()] == 1 && calls[Metric.JDBC_EXECUTE.ordinal()] == 1);
        int expected = observe ? 1 : 0;
        require(calls[Metric.FINGERPRINT.ordinal()] == expected && calls[Metric.EVENT_CREATE.ordinal()] == expected
                && calls[Metric.EVENT_SINK.ordinal()] == expected);
        require(observe ? calls[Metric.OBSERVE_PROXY.ordinal()] > 0 : calls[Metric.OBSERVE_PROXY.ordinal()] == 0);
        long accounted = 0;
        for (long interval : nanos) accounted = Math.addExact(accounted, interval);
        require(accounted <= elapsed);
        nanos[Metric.TOTAL.ordinal()] = elapsed;
        nanos[Metric.OTHER.ordinal()] = elapsed - accounted;
        if (measuredIndex >= 0) {
            for (Metric metric : METRICS) arm.samples[metric.ordinal()][measuredIndex] = nanos[metric.ordinal()];
        }
        arm.completed++;
        active = null;
    }

    public static void report(PrintStream out) {
        require(active == null && !timing && PLAIN.completed == WARMUP + MEASURED
                && OBSERVE.completed == WARMUP + MEASURED);
        reportArm(out, "PLAIN", PLAIN);
        reportArm(out, "OBSERVE", OBSERVE);
    }

    private static void reportArm(PrintStream out, String name, Arm arm) {
        for (Metric metric : METRICS) {
            StringJoiner values = new StringJoiner(",");
            for (long value : arm.samples[metric.ordinal()]) values.add(Long.toString(value));
            out.println("ATTRIBUTION " + name + " " + metric + " " + values);
        }
    }

    private static void require(boolean valid) {
        if (!valid) throw new IllegalStateException("Attribution invariant failed");
    }
}
