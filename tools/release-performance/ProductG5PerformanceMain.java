import dev.udak.observe.FingerprintStatus;
import dev.udak.observe.Framework;
import dev.udak.observe.ObservationPoint;
import dev.udak.observe.ObservationSink;
import dev.udak.observe.SqlObservation;
import dev.udak.observe.SqlObserver;
import dev.udak.observe.StatementKind;
import dev.udak.observe.jdbc.ObserveDataSource;
import java.io.OutputStream;
import java.io.PrintStream;
import java.nio.charset.StandardCharsets;
import java.sql.Connection;
import java.sql.DatabaseMetaData;
import java.sql.DriverManager;
import java.sql.PreparedStatement;
import java.sql.SQLException;
import java.sql.Statement;
import java.util.Arrays;
import java.util.Properties;
import java.util.StringJoiner;
import java.util.concurrent.TimeUnit;
import java.util.logging.LogManager;
import java.util.regex.Pattern;
import javax.sql.DataSource;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DelegatingDataSource;
import org.springframework.jdbc.datasource.SingleConnectionDataSource;

/** Bounded paired JdbcTemplate SELECTs on a single connection to a fresh parent-owned fixture. */
public final class ProductG5PerformanceMain {
    private static final int WARMUP = 8;
    private static final int MEASURED = 96;
    private static final int TOTAL = (WARMUP + MEASURED) * 2;
    private static final int ROWS = 8;
    private static final long INTERVAL_NS = TimeUnit.MILLISECONDS.toNanos(125);
    private static final int TIMEOUT_SECONDS = 3;
    private static final String SELECT =
            "SELECT id, fixture_value FROM udak_perf_fixture WHERE id = ?";

    public static void main(String[] args) {
        PrintStream report = System.out;
        PrintStream discard = new PrintStream(OutputStream.nullOutputStream());
        System.setOut(discard);
        System.setErr(discard);
        LogManager.getLogManager().reset();
        String stage = "SCHEDULE";
        try {
            verifySchedule();
            stage = "INPUT";
            require(args.length == 2 && args[1].matches("[0-9]{1,5}"));
            Engine engine = Engine.valueOf(args[0]);
            int port = Integer.parseInt(args[1]);
            require(port >= 1 && port <= 65535);
            String secret = privateInput();
            DriverManager.setLoginTimeout(2);
            stage = "CONNECT";
            Trial trial;
            try (Connection connection = engine.connect(port, secret)) {
                stage = "IDENTITY";
                engine.verify(connection);
                stage = "SETUP";
                seed(connection, engine);
                trial = new Trial(connection);
                stage = "WORKLOAD";
                trial.run();
                stage = "CLOSE";
            }
            stage = "VERIFY";
            trial.report(engine, report);
        } catch (Exception | LinkageError failure) {
            report.println("PRODUCT_PERF_ERROR stage=" + stage);
            System.exit(1);
        }
    }

    private static int fixtureId(int pair) {
        int rowOffset = pair % ROWS;
        int rowBlock = pair / ROWS;
        // Rotate the rows per block so each ID is measured in both execution orders.
        return 1 + (rowOffset + rowBlock) % ROWS;
    }

    private static void verifySchedule() {
        int[][] measuredByRowAndOrder = new int[ROWS][2];
        for (int pair = WARMUP; pair < WARMUP + MEASURED; pair++) {
            measuredByRowAndOrder[fixtureId(pair) - 1][pair % 2]++;
        }
        require(MEASURED % (ROWS * 2) == 0);
        int expected = MEASURED / (ROWS * 2);
        for (int[] orders : measuredByRowAndOrder) {
            require(orders[0] == expected && orders[1] == expected);
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
            serverVersion = Pattern.compile(Pattern.quote(server) + "(?:[ -][ -~]{0,128})?");
            driverVersion = Pattern.compile(driver);
        }

        Connection connect(int port, String secret) throws Exception {
            String url = "jdbc:" + protocol + "://127.0.0.1:" + port + "/" + catalog;
            Class.forName(driverClass);
            require(DriverManager.getDriver(url).getClass().getName().equals(driverClass));
            Properties properties = new Properties();
            properties.setProperty("user", "udak_fixture");
            properties.setProperty("password", secret);
            if (this == POSTGRESQL) {
                properties.setProperty("ApplicationName", "udak-product-g5");
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

    private static void seed(Connection connection, Engine engine) throws SQLException {
        require(connection.getAutoCommit());
        try (Statement ddl = connection.createStatement()) {
            ddl.setQueryTimeout(TIMEOUT_SECONDS);
            String storage = engine == Engine.MYSQL ? " ENGINE=InnoDB" : "";
            ddl.executeUpdate("CREATE TABLE udak_perf_fixture (id INTEGER PRIMARY KEY, fixture_value INTEGER NOT NULL)" + storage);
        }
        try (PreparedStatement insert = connection.prepareStatement(
                "INSERT INTO udak_perf_fixture (id, fixture_value) VALUES (?, ?)")) {
            insert.setQueryTimeout(TIMEOUT_SECONDS);
            for (int id = 1; id <= ROWS; id++) {
                insert.setInt(1, id);
                insert.setInt(2, valueFor(id));
                require(insert.executeUpdate() == 1);
            }
        }
    }

    private static int valueFor(int id) {
        return 100 + 7 * id;
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

    private static final class Trial {
        private final EventCounter events = new EventCounter();
        private final JdbcTemplate plain;
        private final JdbcTemplate observed;
        private final long[] starts = new long[TOTAL];
        private final long[] plainSamples = new long[MEASURED];
        private final long[] observedSamples = new long[MEASURED];
        private SqlObservation firstEvent;
        private int completed;

        Trial(Connection connection) {
            // Both arms borrow and logically close the same close-suppressed physical connection.
            // The delegate gives both templates the same ordinary (non-SmartDataSource) release path.
            DataSource shared = new DelegatingDataSource(new SingleConnectionDataSource(connection, true));
            plain = new JdbcTemplate(shared);
            observed = new JdbcTemplate(new ObserveDataSource(shared, new SqlObserver(events)));
            plain.setQueryTimeout(TIMEOUT_SECONDS);
            observed.setQueryTimeout(TIMEOUT_SECONDS);
        }

        void run() throws InterruptedException {
            for (int pair = 0; pair < WARMUP + MEASURED; pair++) {
                int id = fixtureId(pair);
                boolean observedFirst = pair % 2 != 0;
                sample(observedFirst, id, pair - WARMUP);
                sample(!observedFirst, id, pair - WARMUP);
            }
        }

        private void sample(boolean observe, int id, int index) throws InterruptedException {
            JdbcTemplate template = observe ? observed : plain;
            int previousEvents = events.count;
            if (completed > 0) {
                long remaining;
                while ((remaining = INTERVAL_NS - (System.nanoTime() - starts[completed - 1])) > 0) {
                    TimeUnit.NANOSECONDS.sleep(remaining);
                }
            }
            long started = System.nanoTime();
            template.query(SELECT, statement -> statement.setInt(1, id), result -> {
                require(result.next() && result.getInt(1) == id && result.getInt(2) == valueFor(id));
                require(!result.next());
                return Boolean.TRUE;
            });
            long elapsed = System.nanoTime() - started;
            require(elapsed > 0 && events.count == previousEvents + (observe ? 1 : 0));
            if (observe) {
                SqlObservation event = events.last;
                require(event.framework() == Framework.JDBC && event.point() == ObservationPoint.JDBC_EXECUTE);
                require(event.statementKind() == StatementKind.SELECT && event.fingerprintStatus() == FingerprintStatus.NORMALIZED);
                if (firstEvent == null) firstEvent = event;
                require(firstEvent.equals(event));
            }
            if (index >= 0) {
                long[] samples = observe ? observedSamples : plainSamples;
                samples[index] = elapsed;
            }
            starts[completed++] = started;
        }

        void report(Engine engine, PrintStream report) {
            require(completed == TOTAL && events.count == WARMUP + MEASURED);
            int maxRolling = 0;
            long minSpacing = Long.MAX_VALUE;
            int left = 0;
            for (int i = 0; i < completed; i++) {
                while (starts[i] - starts[left] >= TimeUnit.SECONDS.toNanos(1)) left++;
                maxRolling = Math.max(maxRolling, i - left + 1);
                if (i > 0) minSpacing = Math.min(minSpacing, starts[i] - starts[i - 1]);
            }
            require(minSpacing >= INTERVAL_NS && maxRolling <= 8);
            String plainLine = samplesLine("PLAIN_NS", plainSamples);
            String observedLine = samplesLine("OBSERVE_NS", observedSamples);
            report.println("PRODUCT_PERF profile=" + engine + " starts=" + completed + " completed=" + completed
                    + " warmup_per_arm=" + WARMUP + " measured_per_arm=" + MEASURED + " verified_rows=" + completed
                    + " events=" + events.count + " errors=0 max_in_flight=1 max_rolling_second=" + maxRolling
                    + " min_spacing_ns=" + minSpacing);
            report.println(plainLine);
            report.println(observedLine);
        }

        private static String samplesLine(String name, long[] samples) {
            StringJoiner values = new StringJoiner(",");
            for (long nanos : samples) {
                require(nanos > 0);
                values.add(Long.toString(nanos));
            }
            return name + " " + values;
        }
    }

    private static void require(boolean condition) {
        if (!condition) throw new IllegalStateException();
    }
}
