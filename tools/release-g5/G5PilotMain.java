import java.io.OutputStream;
import java.io.PrintStream;
import java.nio.charset.StandardCharsets;
import java.sql.*;
import java.util.Arrays;
import java.util.Properties;
import java.util.concurrent.*;
import java.util.logging.LogManager;
import java.util.regex.Pattern;

/** One run against a fresh, parent-owned native fixture. Only aggregate metrics reach stdout. */
public final class G5PilotMain {
    private static final int OPERATIONS = 48;
    private static final long SPACING = TimeUnit.MILLISECONDS.toNanos(250);
    private static final String TABLE = "udak_g5_fixture";
    private static final String FETCH = "SELECT fixture_value FROM " + TABLE + " WHERE id = ?";
    private static final String ADD = "UPDATE " + TABLE + " SET fixture_value = fixture_value + ? WHERE id = ?";
    private static final int QUERY_SECONDS = 3;

    public static void main(String[] args) {
        PrintStream report = System.out;
        PrintStream discard = new PrintStream(OutputStream.nullOutputStream());
        System.setOut(discard);
        System.setErr(discard);
        LogManager.getLogManager().reset();
        String stage = "INPUT";
        try {
            require(args.length == 2 && args[1].matches("[0-9]{1,5}"));
            Engine engine = Engine.valueOf(args[0]);
            int port = Integer.parseInt(args[1]);
            require(port > 0 && port <= 65535);
            String password = privateInput();
            DriverManager.setLoginTimeout(2);
            stage = "CONNECT";
            try (Connection setup = engine.connect(port, password)) {
                stage = "IDENTITY";
                engine.verify(setup);
                stage = "SETUP";
                seed(setup, engine);
            }
            Metrics metrics = new Metrics();
            stage = "CONNECT";
            try (Connection first = engine.connect(port, password);
                 Connection second = engine.connect(port, password)) {
                stage = "WORKLOAD";
                first.setAutoCommit(false);
                second.setAutoCommit(false);
                exercise(first, second, metrics);
                stage = "CLOSE";
            }
            stage = "VERIFY";
            int verified;
            try (Connection independent = engine.connect(port, password)) {
                verified = verifyRows(independent);
                stage = "CLOSE";
            }
            stage = "VERIFY";
            report.println(metrics.summary(engine, verified));
        } catch (Exception | LinkageError failure) {
            report.println("G5_ERROR stage=" + stage);
            System.exit(1);
        }
    }

    private static String privateInput() throws Exception {
        byte[] input = System.in.readNBytes(130);
        try {
            int length = input.length - 1;
            require(length > 0 && length <= 128 && input[length] == '\n');
            for (int i = 0; i < length; i++) require(input[i] >= 32 && input[i] <= 126);
            return new String(input, 0, length, StandardCharsets.US_ASCII);
        } finally {
            Arrays.fill(input, (byte) 0);
        }
    }

    private enum Engine {
        POSTGRESQL("postgresql", "postgres", "PostgreSQL", "org.postgresql.Driver",
                "PostgreSQL JDBC Driver", "17.11", Pattern.quote("42.7.14")),
        MYSQL("mysql", "udak_fixture", "MySQL", "com.mysql.cj.jdbc.Driver",
                "MySQL Connector/J", "8.0.46", "mysql-connector-j-26\\.10\\.0 \\(Revision: [A-Za-z0-9._-]{1,128}\\)");

        final String protocol, catalog, product, driverClass, driverName;
        final Pattern serverVersion, driverVersion;

        Engine(String protocol, String catalog, String product, String driverClass,
               String driverName, String server, String driver) {
            this.protocol = protocol;
            this.catalog = catalog;
            this.product = product;
            this.driverClass = driverClass;
            this.driverName = driverName;
            this.serverVersion = Pattern.compile(Pattern.quote(server) + "(?:[ -][ -~]{0,128})?");
            this.driverVersion = Pattern.compile(driver);
        }

        Connection connect(int port, String password) throws Exception {
            String url = "jdbc:" + protocol + "://127.0.0.1:" + port + "/" + catalog;
            Class.forName(driverClass);
            require(DriverManager.getDriver(url).getClass().getName().equals(driverClass));
            Properties properties = new Properties();
            properties.setProperty("user", "udak_fixture");
            properties.setProperty("password", password);
            if (this == POSTGRESQL) {
                properties.setProperty("ApplicationName", "udak-g5");
                properties.setProperty("currentSchema", "public");
                properties.setProperty("sslmode", "disable");
                properties.setProperty("gssEncMode", "disable");
                properties.setProperty("connectTimeout", "2");
                properties.setProperty("cancelSignalTimeout", "2");
                properties.setProperty("socketTimeout", "6");
                properties.setProperty("options", "-c statement_timeout=3000 -c lock_timeout=2500");
            } else {
                properties.setProperty("connectTimeout", "2000");
                properties.setProperty("socketTimeout", "6000");
                properties.setProperty("autoReconnect", "false");
                properties.setProperty("sslMode", "DISABLED");
                properties.setProperty("logger", "com.mysql.cj.log.NullLogger");
                properties.setProperty("useServerPrepStmts", "true");
                properties.setProperty("sessionVariables", "max_execution_time=3000,lock_wait_timeout=3,innodb_lock_wait_timeout=3");
            }
            try {
                return DriverManager.getConnection(url, properties);
            } finally {
                properties.remove("password");
            }
        }

        void verify(Connection connection) throws SQLException {
            DatabaseMetaData metadata = connection.getMetaData();
            require(catalog.equals(connection.getCatalog()));
            require(this != POSTGRESQL || "public".equals(connection.getSchema()));
            require(product.equals(metadata.getDatabaseProductName()) && driverName.equals(metadata.getDriverName()));
            require(serverVersion.matcher(metadata.getDatabaseProductVersion()).matches());
            require(driverVersion.matcher(metadata.getDriverVersion()).matches());
        }
    }

    private static void seed(Connection setup, Engine engine) throws SQLException {
        try (Statement ddl = setup.createStatement()) {
            ddl.setQueryTimeout(QUERY_SECONDS);
            String storage = engine == Engine.MYSQL ? " ENGINE=InnoDB" : "";
            ddl.executeUpdate("CREATE TABLE " + TABLE + " (id INTEGER PRIMARY KEY, fixture_value INTEGER NOT NULL)" + storage);
        }
        setup.setAutoCommit(false);
        try (PreparedStatement insert = setup.prepareStatement("INSERT INTO " + TABLE + " (id, fixture_value) VALUES (?, ?)")) {
            insert.setQueryTimeout(QUERY_SECONDS);
            for (int id = 1; id <= OPERATIONS; id++) {
                insert.setInt(1, id);
                insert.setInt(2, id);
                insert.addBatch();
            }
            int[] counts = insert.executeBatch();
            require(counts.length == OPERATIONS);
            for (int count : counts) require(count == 1 || count == Statement.SUCCESS_NO_INFO);
        }
        setup.commit();
    }

    private enum Operation {
        COMMIT, ROLLBACK, READ;
        static Operation forRow(int id) { return values()[(id - 1) % values().length]; }
    }

    private record FirstPair(CountDownLatch firstWrite, CountDownLatch secondWrite) {
        FirstPair() { this(new CountDownLatch(1), new CountDownLatch(1)); }
    }

    private static void exercise(Connection first, Connection second, Metrics metrics) throws Exception {
        FirstPair pair = new FirstPair();
        ExecutorService worker = Executors.newSingleThreadExecutor();
        try {
            Future<Void> firstTransaction = worker.submit(() -> {
                runOne(first, 1, metrics, pair);
                return null;
            });
            require(pair.firstWrite().await(5, TimeUnit.SECONDS));
            runOne(second, 2, metrics, pair);
            firstTransaction.get(5, TimeUnit.SECONDS);
        } finally {
            worker.shutdownNow();
            require(worker.awaitTermination(7, TimeUnit.SECONDS));
        }
        for (int id = 3; id <= OPERATIONS; id++) {
            runOne(id % 2 == 1 ? first : second, id, metrics, null);
        }
    }

    private static void runOne(Connection connection, int id, Metrics metrics, FirstPair pair) throws Exception {
        Operation operation = Operation.forRow(id);
        metrics.start();
        long started = System.nanoTime();
        long excluded = 0;
        if (operation == Operation.READ) {
            try (PreparedStatement read = connection.prepareStatement(FETCH)) {
                read.setQueryTimeout(QUERY_SECONDS);
                read.setInt(1, id);
                try (ResultSet row = read.executeQuery()) {
                    require(row.next() && row.getInt(1) == id && !row.next());
                }
            }
        } else {
            try (PreparedStatement write = connection.prepareStatement(ADD)) {
                write.setQueryTimeout(QUERY_SECONDS);
                write.setInt(1, 1);
                write.setInt(2, id);
                require(write.executeUpdate() == 1);
            }
            if (pair != null) {
                // Both distinct writes have executed while transaction one still holds its row.
                long barrier = System.nanoTime();
                if (id == 1) {
                    pair.firstWrite().countDown();
                    require(pair.secondWrite().await(5, TimeUnit.SECONDS));
                } else {
                    pair.secondWrite().countDown();
                }
                excluded = System.nanoTime() - barrier;
            }
        }
        if (operation == Operation.ROLLBACK) connection.rollback();
        else connection.commit();
        metrics.finish(operation, System.nanoTime() - started - excluded);
    }

    private static int verifyRows(Connection independent) throws SQLException {
        int count = 0;
        try (Statement check = independent.createStatement()) {
            check.setQueryTimeout(QUERY_SECONDS);
            try (ResultSet rows = check.executeQuery("SELECT id, fixture_value FROM " + TABLE + " ORDER BY id")) {
                while (rows.next()) {
                    int id = ++count;
                    int expected = Operation.forRow(id) == Operation.COMMIT ? id + 1 : id;
                    require(id <= OPERATIONS && rows.getInt(1) == id && rows.getInt(2) == expected);
                }
            }
        }
        require(count == OPERATIONS);
        return count;
    }

    private static final class Metrics {
        final long[] starts = new long[OPERATIONS];
        final long[] durations = new long[OPERATIONS];
        final int[] counts = new int[Operation.values().length];
        int started, finished, active, peak;

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

        synchronized void finish(Operation operation, long nanos) {
            require(active > 0 && nanos > 0);
            durations[finished++] = nanos;
            counts[operation.ordinal()]++;
            active--;
        }

        String summary(Engine engine, int verified) {
            require(active == 0 && started == OPERATIONS && finished == OPERATIONS && peak == 2);
            for (int count : counts) require(count == OPERATIONS / 3);
            int rolling = 0, left = 0;
            long minGap = Long.MAX_VALUE;
            for (int i = 0; i < started; i++) {
                while (starts[i] - starts[left] >= TimeUnit.SECONDS.toNanos(1)) left++;
                rolling = Math.max(rolling, i - left + 1);
                if (i > 0) minGap = Math.min(minGap, starts[i] - starts[i - 1]);
            }
            require(rolling <= 4 && minGap >= SPACING);
            Arrays.sort(durations);
            return "G5_RESULT profile=" + engine + " starts=" + started + " completed=" + finished
                    + " reads=" + counts[Operation.READ.ordinal()] + " commits=" + counts[Operation.COMMIT.ordinal()]
                    + " rollbacks=" + counts[Operation.ROLLBACK.ordinal()] + " verified=" + verified
                    + " errors=0 max_in_flight=" + peak + " max_rolling_second=" + rolling
                    + " min_spacing_us=" + TimeUnit.NANOSECONDS.toMicros(minGap)
                    + " p50_us=" + percentile(50) + " p95_us=" + percentile(95) + " max_us=" + percentile(100);
        }

        long percentile(int percent) {
            int rank = (finished * percent + 99) / 100;
            return TimeUnit.NANOSECONDS.toMicros(durations[rank - 1]);
        }
    }

    private static void require(boolean condition) {
        if (!condition) throw new IllegalStateException();
    }
}
