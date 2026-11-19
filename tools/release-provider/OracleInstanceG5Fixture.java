import java.io.OutputStream;
import java.io.PrintStream;
import java.nio.charset.StandardCharsets;
import java.sql.Connection;
import java.sql.DatabaseMetaData;
import java.sql.DriverManager;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Statement;
import java.util.Arrays;
import java.util.Properties;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.CyclicBarrier;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;
import java.util.logging.LogManager;

/** Fixed Oracle Free transaction and instance recovery checks, driven by the local supervisor. */
public final class OracleInstanceG5Fixture {
    private static final String PIN = "23.26.4.0.0";
    private static final String WORK = "G5_INSTANCE_CONCURRENCY";
    private static final String CRASH = "G5_INSTANCE_CRASH";
    private static final int OPERATIONS = 48;
    private static final int QUERY_SECONDS = 5;
    private static final long SPACING = TimeUnit.MILLISECONDS.toNanos(250);
    private final String url;
    private final String schema;
    private final Properties options = new Properties();

    private OracleInstanceG5Fixture(String port, String schema, String secret) {
        require(port.matches("[0-9]{1,5}") && Integer.parseInt(port) > 0 && Integer.parseInt(port) <= 65535);
        require(schema.matches("UDAKG5[0-9A-F]{24}") && secret.matches("ABab12#_[0-9a-f]{22}"));
        this.url = "jdbc:oracle:thin:@//127.0.0.1:" + port + "/FREEPDB1";
        this.schema = schema;
        options.setProperty("user", schema);
        options.setProperty("password", secret);
        options.setProperty("oracle.net.CONNECT_TIMEOUT", "3000");
        options.setProperty("oracle.jdbc.ReadTimeout", "12000");
    }

    private static OracleInstanceG5Fixture input() throws Exception {
        byte[] bytes = System.in.readNBytes(96);
        try {
            require(bytes.length > 0 && bytes.length < 96);
            String[] fields = new String(bytes, StandardCharsets.US_ASCII).split("\\r?\\n", -1);
            require(fields.length == 3 || (fields.length == 4 && fields[3].isEmpty()));
            return new OracleInstanceG5Fixture(fields[0], fields[1], fields[2]);
        } finally {
            Arrays.fill(bytes, (byte) 0);
        }
    }

    private static void require(boolean condition) {
        if (!condition) throw new IllegalStateException();
    }

    private static void emit(PrintStream protocol, String message) {
        protocol.println(message);
        protocol.flush();
    }

    private static String scalar(Connection c, String sql) throws SQLException {
        try (Statement s = c.createStatement()) {
            s.setQueryTimeout(QUERY_SECONDS);
            try (ResultSet r = s.executeQuery(sql)) {
                require(r.next());
                String value = r.getString(1);
                require(!r.next());
                return value;
            }
        }
    }

    private Connection connect() throws SQLException {
        Connection c = DriverManager.getConnection(url, options);
        try {
            DatabaseMetaData metadata = c.getMetaData();
            require("Oracle".equals(metadata.getDatabaseProductName()));
            require("Oracle JDBC driver".equalsIgnoreCase(metadata.getDriverName()));
            require(PIN.equals(metadata.getDriverVersion()));
            require(PIN.equals(scalar(c, "select version_full from product_component_version where product like 'Oracle%'")));
            require("FREEPDB1".equals(scalar(c, "select sys_context('USERENV','CON_NAME') from dual")));
            require(schema.equals(scalar(c, "select sys_context('USERENV','SESSION_USER') from dual")));
            require(schema.equals(scalar(c, "select sys_context('USERENV','CURRENT_SCHEMA') from dual")));
            c.setAutoCommit(false);
            return c;
        } catch (SQLException | RuntimeException failure) {
            c.close();
            throw failure;
        }
    }

    private static void create(Connection c, String table) throws SQLException {
        try (Statement s = c.createStatement()) {
            s.setQueryTimeout(QUERY_SECONDS);
            s.executeUpdate("create table " + table + " (id number(9) primary key, marker number(9) not null)");
        }
    }

    private static void write(Connection c, String sql, int id, int marker) throws SQLException {
        try (PreparedStatement s = c.prepareStatement(sql)) {
            s.setQueryTimeout(QUERY_SECONDS);
            s.setInt(1, marker);
            s.setInt(2, id);
            require(s.executeUpdate() == 1);
        }
    }

    private static void verify(Connection c, String table, int id, Integer expected) throws SQLException {
        try (PreparedStatement s = c.prepareStatement("select marker from " + table + " where id = ?")) {
            s.setQueryTimeout(QUERY_SECONDS);
            s.setInt(1, id);
            try (ResultSet r = s.executeQuery()) {
                if (expected != null) require(r.next() && r.getInt(1) == expected && !r.wasNull());
                require(!r.next());
            }
        }
    }

    private enum Operation {
        COMMIT, ROLLBACK, READ;
        static Operation forId(int id) { return values()[(id - 1) % 3]; }
    }

    private static final class Metrics {
        private final long[] starts = new long[OPERATIONS];
        private final int[] completed = new int[Operation.values().length];
        private int started, active, peak;

        synchronized void start() throws InterruptedException {
            require(started < OPERATIONS && active < 2);
            if (started > 0) {
                long wait;
                while ((wait = SPACING - (System.nanoTime() - starts[started - 1])) > 0) {
                    TimeUnit.NANOSECONDS.sleep(wait);
                }
            }
            starts[started++] = System.nanoTime();
            peak = Math.max(peak, ++active);
        }

        synchronized void finish(Operation op) {
            require(active > 0);
            completed[op.ordinal()]++;
            active--;
        }

        String result() {
            require(started == OPERATIONS && active == 0 && peak == 2);
            for (int count : completed) require(count == 16);
            int maxRolling = 0, left = 0;
            long minGap = Long.MAX_VALUE;
            for (int i = 0; i < started; i++) {
                while (starts[i] - starts[left] >= TimeUnit.SECONDS.toNanos(1)) left++;
                maxRolling = Math.max(maxRolling, i - left + 1);
                if (i > 0) minGap = Math.min(minGap, starts[i] - starts[i - 1]);
            }
            require(maxRolling <= 4 && minGap >= SPACING);
            return "ORACLE_INSTANCE CONCURRENCY PASS " + started + " " + peak + " " + maxRolling + " " + minGap;
        }
    }

    private record FirstPair(CountDownLatch firstWritten, CyclicBarrier both) {
        FirstPair() { this(new CountDownLatch(1), new CyclicBarrier(2)); }

        void verifyIsolation(Connection c, int id) throws Exception {
            if (id == 1) firstWritten.countDown();
            both.await(8, TimeUnit.SECONDS);
            // Both sessions hold a distinct modified row. Neither may finish before both reads.
            int otherId = 3 - id;
            verify(c, WORK, otherId, otherId);
            both.await(8, TimeUnit.SECONDS);
        }
    }

    private static void runOne(Connection c, int id, Metrics metrics, FirstPair pair) throws Exception {
        Operation op = Operation.forId(id);
        metrics.start();
        if (op == Operation.READ) {
            verify(c, WORK, id, id);
        } else {
            write(c, "update " + WORK + " set marker = ? where id = ?", id, id + 100);
            verify(c, WORK, id, id + 100);
            if (pair != null) pair.verifyIsolation(c, id);
        }
        if (op == Operation.ROLLBACK) c.rollback();
        else c.commit();
        metrics.finish(op);
    }

    private static void firstTwo(Connection first, Connection second, Metrics metrics) throws Exception {
        FirstPair pair = new FirstPair();
        ExecutorService worker = Executors.newSingleThreadExecutor();
        try {
            Future<Void> one = worker.submit(() -> {
                runOne(first, 1, metrics, pair);
                return null;
            });
            require(pair.firstWritten.await(8, TimeUnit.SECONDS));
            runOne(second, 2, metrics, pair);
            one.get(8, TimeUnit.SECONDS);
        } finally {
            worker.shutdownNow();
            require(worker.awaitTermination(15, TimeUnit.SECONDS));
        }
    }

    private String concurrency() throws Exception {
        Metrics metrics = new Metrics();
        try (Connection first = connect(); Connection second = connect()) {
            create(first, WORK);
            try (PreparedStatement seed = first.prepareStatement("insert into " + WORK
                    + " (id, marker) select level, level from dual connect by level <= ?")) {
                seed.setQueryTimeout(QUERY_SECONDS);
                seed.setInt(1, OPERATIONS);
                require(seed.executeUpdate() == OPERATIONS);
            }
            first.commit();
            firstTwo(first, second, metrics);
            for (int id = 3; id <= OPERATIONS; id++) {
                runOne(id % 2 == 1 ? first : second, id, metrics, null);
            }
        }
        try (Connection independent = connect(); Statement check = independent.createStatement()) {
            check.setQueryTimeout(QUERY_SECONDS);
            try (ResultSet rows = check.executeQuery("select id, marker from " + WORK + " order by id")) {
                for (int id = 1; id <= OPERATIONS; id++) {
                    int expected = Operation.forId(id) == Operation.COMMIT ? id + 100 : id;
                    require(rows.next() && rows.getInt(1) == id && rows.getInt(2) == expected);
                }
                require(!rows.next());
            }
        }
        return metrics.result();
    }

    private static void insertCrashRow(Connection c, int id) throws SQLException {
        write(c, "insert into " + CRASH + " (marker, id) values (?, ?)", id, id * 10);
    }

    private void seed(PrintStream protocol) throws Exception {
        try (Connection writer = connect(); Connection observer = connect()) {
            create(writer, CRASH);
            insertCrashRow(writer, 1);
            writer.commit();
            verify(observer, CRASH, 1, 10);
            try {
                insertCrashRow(writer, 2);
                verify(writer, CRASH, 2, 20);
                verify(observer, CRASH, 2, null);
                emit(protocol, "ORACLE_INSTANCE SEED READY");
                TimeUnit.SECONDS.sleep(60);
                throw new TimeoutException();
            } finally {
                writer.rollback();
            }
        }
    }

    private void recover() throws Exception {
        try (Connection writer = connect(); Connection observer = connect()) {
            verify(writer, CRASH, 1, 10);
            verify(writer, CRASH, 2, null);
            try {
                insertCrashRow(writer, 3);
                verify(observer, CRASH, 3, null);
                writer.commit();
            } catch (SQLException | RuntimeException failure) {
                writer.rollback();
                throw failure;
            }
            verify(observer, CRASH, 1, 10);
            verify(observer, CRASH, 2, null);
            verify(observer, CRASH, 3, 30);
            require("2".equals(scalar(observer, "select count(*) from " + CRASH)));
        }
    }

    private enum Mode { CONCURRENCY, SEED, RECOVER }

    public static void main(String[] args) {
        PrintStream protocol = System.out;
        PrintStream discard = new PrintStream(OutputStream.nullOutputStream());
        System.setOut(discard);
        System.setErr(discard);
        LogManager.getLogManager().reset();
        String stage = "INPUT";
        try {
            require(args.length == 1);
            Mode mode = Mode.valueOf(args[0]);
            OracleInstanceG5Fixture fixture = input();
            DriverManager.setLoginTimeout(5);
            stage = mode.name();
            switch (mode) {
                case CONCURRENCY -> emit(protocol, fixture.concurrency());
                case SEED -> fixture.seed(protocol);
                case RECOVER -> {
                    fixture.recover();
                    emit(protocol, "ORACLE_INSTANCE RECOVER PASS");
                }
            }
        } catch (Exception | LinkageError failure) {
            Throwable cause = failure instanceof ExecutionException ? failure.getCause() : failure;
            String family = cause instanceof SQLException ? "SQL" : cause instanceof TimeoutException ? "TIMEOUT" : "CHECK";
            emit(protocol, "ORACLE_INSTANCE FAIL " + stage + " " + family);
            System.exit(1);
        }
    }
}
