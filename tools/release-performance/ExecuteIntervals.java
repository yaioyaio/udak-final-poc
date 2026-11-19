package dev.udak.diagnostic;

import java.lang.management.ManagementFactory;
import java.lang.management.ThreadMXBean;
import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Method;
import java.lang.reflect.Proxy;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;

/** Measures one prepared SELECT on the connection shared by the diagnostic paths. */
public final class ExecuteIntervals {
    public record Sample(long jdbcWall, long threadCpu, long readNs, long writeNs,
                         long readCalls, long writeCalls, long readBytes, long writeBytes) {}

    private static final ThreadMXBean THREADS = ManagementFactory.getThreadMXBean();
    private static final ThreadLocal<Measurement> ACTIVE = new ThreadLocal<>();

    public ExecuteIntervals() {
        if (!THREADS.isCurrentThreadCpuTimeSupported() || !THREADS.isThreadCpuTimeEnabled()) {
            throw new IllegalStateException("Calling-thread CPU timing is unavailable");
        }
    }

    public void begin() {
        if (ACTIVE.get() != null) throw new IllegalStateException("Execute capture is already active");
        ACTIVE.set(new Measurement(this));
    }

    public Sample finish() {
        Measurement measurement = ACTIVE.get();
        if (measurement == null || measurement.owner != this || measurement.executing) {
            throw new IllegalStateException("No finished execute capture on the calling thread");
        }
        ACTIVE.remove();
        if (measurement.executeCalls != 1 || !measurement.completed
                || measurement.jdbcWall <= 0 || measurement.threadCpu < 0
                || measurement.threadCpu > measurement.jdbcWall
                || measurement.readNs + measurement.writeNs > measurement.jdbcWall) {
            throw new IllegalStateException("Invalid execute timing sample");
        }
        return new Sample(measurement.jdbcWall, measurement.threadCpu, measurement.readNs, measurement.writeNs,
                measurement.readCalls, measurement.writeCalls, measurement.readBytes, measurement.writeBytes);
    }

    public void cancel() {
        Measurement measurement = ACTIVE.get();
        if (measurement != null && measurement.owner == this) ACTIVE.remove();
    }

    public Connection wrap(Connection connection) {
        return (Connection) Proxy.newProxyInstance(Connection.class.getClassLoader(), new Class<?>[] {Connection.class},
                (self, method, args) -> {
                    if (method.getDeclaringClass() == Object.class) return proxyIdentity(self, method, args);
                    Object result = invoke(connection, method, args);
                    if (method.getName().equals("prepareStatement")) {
                        return wrapStatement((PreparedStatement) result, (Connection) self);
                    }
                    return result;
                });
    }

    private PreparedStatement wrapStatement(PreparedStatement statement, Connection connection) {
        return (PreparedStatement) Proxy.newProxyInstance(PreparedStatement.class.getClassLoader(),
                new Class<?>[] {PreparedStatement.class}, (self, method, args) -> {
                    if (method.getDeclaringClass() == Object.class) return proxyIdentity(self, method, args);
                    if (method.getName().equals("executeQuery") && method.getParameterCount() == 0) {
                        return execute(statement);
                    }
                    Object result = invoke(statement, method, args);
                    return method.getName().equals("getConnection") && result != null ? connection : result;
                });
    }

    private ResultSet execute(PreparedStatement statement) throws SQLException {
        Measurement measurement = ACTIVE.get();
        if (measurement == null || measurement.owner != this) return statement.executeQuery();
        measurement.executeCalls++;
        if (measurement.executeCalls != 1) throw new IllegalStateException("Capture requires one prepared query");

        long wallStart = System.nanoTime();
        long cpuStart = THREADS.getCurrentThreadCpuTime();
        if (cpuStart < 0) throw new IllegalStateException("Calling-thread CPU timing is unavailable");
        measurement.executing = true;
        try {
            ResultSet rows = statement.executeQuery();
            long cpuStop = THREADS.getCurrentThreadCpuTime();
            long wallStop = System.nanoTime();
            measurement.jdbcWall = wallStop - wallStart;
            measurement.threadCpu = cpuStop - cpuStart;
            measurement.completed = true;
            return rows;
        } finally {
            measurement.executing = false;
        }
    }

    static Measurement activeSocketCapture() {
        Measurement measurement = ACTIVE.get();
        return measurement != null && measurement.executing ? measurement : null;
    }

    static final class Measurement {
        private final ExecuteIntervals owner;
        private int executeCalls;
        private boolean executing;
        private boolean completed;
        private long jdbcWall;
        private long threadCpu;
        private long readNs;
        private long writeNs;
        private long readCalls;
        private long writeCalls;
        private long readBytes;
        private long writeBytes;

        private Measurement(ExecuteIntervals owner) {
            this.owner = owner;
        }

        void recordRead(long start, long bytes) {
            readNs += System.nanoTime() - start;
            readCalls++;
            if (bytes > 0) readBytes += bytes;
        }

        void recordWrite(long start, long bytes) {
            writeNs += System.nanoTime() - start;
            writeCalls++;
            if (bytes > 0) writeBytes += bytes;
        }
    }

    private static Object invoke(Object target, Method method, Object[] args) throws Throwable {
        try {
            return method.invoke(target, args);
        } catch (InvocationTargetException wrapped) {
            throw wrapped.getCause();
        }
    }

    private static Object proxyIdentity(Object self, Method method, Object[] args) {
        return switch (method.getName()) {
            case "equals" -> self == args[0];
            case "hashCode" -> System.identityHashCode(self);
            case "toString" -> "ExecuteIntervalJdbcProxy";
            default -> throw new IllegalStateException("Unexpected JDBC proxy object method");
        };
    }
}
