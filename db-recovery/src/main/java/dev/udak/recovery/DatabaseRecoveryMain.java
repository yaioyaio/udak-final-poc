package dev.udak.recovery;

import java.io.IOException;
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
import java.util.concurrent.FutureTask;
import java.util.concurrent.TimeUnit;
import java.util.logging.LogManager;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** Invoked by the protected runner with one disposable native database. */
public final class DatabaseRecoveryMain {
    private static final String TABLE = "udak_recovery_fixture";
    private static final String READ = "SELECT fixture_value FROM " + TABLE + " WHERE id = ?";
    private static final String UPDATE = "UPDATE " + TABLE + " SET fixture_value = ? WHERE id = ?";
    private static final String SELECT_FOR_UPDATE = READ + " FOR UPDATE NOWAIT";
    private static final int STATEMENT_SECONDS = 3;
    private static final int POLL_MILLIS = 1500;
    private static final int POLL_INTERVAL_MILLIS = 50;
    private static final int BASELINE = 0;
    private static final int BLOCKER_WRITE = 1;
    private static final int BLOCKED_WRITE = 2;
    private static final int UNCOMMITTED_WRITE = 3;
    private static final int RECOVERY_WRITE = 4;
    private static final Pattern SERVER_VERSION = Pattern.compile(
            "([0-9]{1,3}(?:\\.[0-9]{1,4}){1,3})(?:[ -][ -~]*)?");

    private DatabaseRecoveryMain() {}

    public static void main(String[] args) {
        PrintStream report = System.out;
        PrintStream discard = new PrintStream(OutputStream.nullOutputStream());
        System.setOut(discard);
        System.setErr(discard);
        LogManager.getLogManager().reset();

        Proof proof = new Proof();
        Engine engine = null;
        try {
            require(args.length == 2 && args[1].matches("[0-9]{1,5}"));
            engine = Engine.valueOf(args[0]);
            int port = Integer.parseInt(args[1]);
            require(port > 0 && port <= 65535);
            proof.stage = Stage.INPUT;
            String password = readPassword();
            proof.stage = Stage.CONNECT;
            Class.forName(engine.driverClass);
            DriverManager.setLoginTimeout(2);
            try (Connection observer = engine.connect(port, password)) {
                proof.stage = Stage.IDENTITY;
                String version = engine.verifiedVersion(observer);
                long observerId = sessionId(observer, engine);
                require(ownedSession(observer, engine, observerId));
                proof.stage = Stage.FIXTURE;
                prepare(observer, engine);
                report.println("RECOVERY_VERSION profile=" + engine + " database=" + version
                        + " driver=" + engine.expectedDriverVersion);
                for (Scenario scenario : Scenario.values()) {
                    proof.begin(scenario);
                    SQLException trigger;
                    try (Connection worker = engine.connect(port, password)) {
                        long workerId = sessionId(worker, engine);
                        proof.check(workerId != observerId && ownedSession(observer, engine, workerId));
                        if (scenario == Scenario.SESSION_LOSS) {
                            trigger = sessionLoss(observer, worker, workerId, engine, port, password, proof);
                        } else {
                            try (Connection blocker = engine.connect(port, password)) {
                                long blockerId = sessionId(blocker, engine);
                                proof.check(blockerId != workerId && blockerId != observerId
                                        && ownedSession(observer, engine, blockerId));
                                trigger = cancelOrTimeout(observer, blocker, blockerId, worker, workerId, engine, proof);
                            }
                        }
                        proof.stage = Stage.CLOSE;
                    }
                    report.println(proof.result(engine, trigger));
                }
            }
        } catch (Exception | LinkageError failure) {
            report.println("RECOVERY_ERROR profile=" + (engine == null ? "UNKNOWN" : engine)
                    + " scenario=" + (proof.scenario == null ? "SETUP" : proof.scenario)
                    + " stage=" + proof.stage + " sqlstate=" + sqlState(failure)
                    + " exception=" + exceptionType(failure));
            System.exit(1);
        }
    }

    private static String readPassword() throws IOException, FixtureFailure {
        byte[] bytes = System.in.readNBytes(130);
        try {
            int length = bytes.length - 1;
            require(length > 0 && length <= 128 && bytes[length] == '\n');
            for (int index = 0; index < length; index++) {
                require(bytes[index] >= 32 && bytes[index] <= 126);
            }
            return new String(bytes, 0, length, StandardCharsets.US_ASCII);
        } finally {
            Arrays.fill(bytes, (byte) 0);
        }
    }

    private static void prepare(Connection observer, Engine engine) throws Exception {
        String suffix = engine == Engine.MYSQL ? " ENGINE=InnoDB" : "";
        execute(observer, "CREATE TABLE " + TABLE + " (id INTEGER PRIMARY KEY, fixture_value INTEGER NOT NULL)"
                + suffix);
        try (PreparedStatement insert = observer.prepareStatement(
                "INSERT INTO " + TABLE + " (id, fixture_value) VALUES (?, ?)")) {
            insert.setQueryTimeout(STATEMENT_SECONDS);
            insert.setInt(2, BASELINE);
            for (Scenario scenario : Scenario.values()) {
                insert.setInt(1, scenario.target);
                require(insert.executeUpdate() == 1);
                insert.setInt(1, scenario.marker);
                require(insert.executeUpdate() == 1);
            }
        }
    }

    private static SQLException cancelOrTimeout(Connection observer, Connection blocker, long blockerId,
                                                 Connection worker, long workerId, Engine engine, Proof proof)
            throws Exception {
        Scenario scenario = proof.scenario;
        proof.stage = Stage.BLOCKER;
        blocker.setAutoCommit(false);
        proof.check(write(blocker, scenario.target, BLOCKER_WRITE) == 1);
        assertRowLocked(observer, scenario.target, engine, proof);

        proof.stage = Stage.MARKER;
        worker.setAutoCommit(false);
        proof.check(write(worker, scenario.marker, UNCOMMITTED_WRITE) == 1);
        proof.check(scalar(observer, READ, scenario.marker) == BASELINE);

        SQLException trigger = runBlockedUpdate(observer, blockerId, worker, workerId, engine, proof);

        proof.stage = Stage.TRANSACTION;
        if (engine == Engine.POSTGRESQL) {
            SQLException rejected = sqlFailure(() -> scalar(worker, READ, scenario.marker));
            proof.checkSql("25P02".equals(sqlState(rejected)), rejected);
        } else {
            proof.check(scalar(worker, READ, scenario.marker) == UNCOMMITTED_WRITE);
        }
        proof.check(scalar(observer, READ, scenario.marker) == BASELINE);

        proof.stage = Stage.ROLLBACK;
        worker.rollback();
        proof.check(scalar(worker, READ, scenario.marker) == BASELINE);
        assertRowLocked(observer, scenario.target, engine, proof);
        blocker.rollback();
        proof.check(scalar(observer, READ, scenario.target) == BASELINE);

        proof.stage = Stage.FOLLOWUP;
        proof.check(sessionId(worker, engine) == workerId && ownedSession(observer, engine, workerId));
        proof.check(write(worker, scenario.marker, RECOVERY_WRITE) == 1);
        worker.commit();
        proof.check(scalar(observer, READ, scenario.marker) == RECOVERY_WRITE);
        proof.check(scalar(observer, READ, scenario.target) == BASELINE);
        return trigger;
    }

    private static SQLException runBlockedUpdate(Connection observer, long blockerId, Connection worker,
                                                   long workerId, Engine engine, Proof proof) throws Exception {
        Scenario scenario = proof.scenario;
        try (PreparedStatement write = worker.prepareStatement(UPDATE)) {
            boolean timeout = scenario == Scenario.JDBC_TIMEOUT;
            write.setQueryTimeout(timeout ? STATEMENT_SECONDS : 0);
            write.setInt(1, BLOCKED_WRITE);
            write.setInt(2, scenario.target);

            FutureTask<Attempt> task = new FutureTask<>(() -> {
                long started = System.nanoTime();
                SQLException failure = sqlFailure(write::executeUpdate);
                return new Attempt(failure, TimeUnit.NANOSECONDS.toMillis(System.nanoTime() - started));
            });
            Thread thread = new Thread(task, "udak-recovery-worker");
            thread.setDaemon(true);
            proof.stage = Stage.BLOCKED;
            thread.start();
            try {
                await(() -> activeWrite(observer, engine, workerId, scenario.target, blockerId));
                Thread.sleep(POLL_INTERVAL_MILLIS);
                proof.check(activeWrite(observer, engine, workerId, scenario.target, blockerId));
                proof.check(!task.isDone());

                proof.stage = Stage.TRIGGER;
                if (!timeout) write.cancel();
                Attempt attempt = task.get(5, TimeUnit.SECONDS);
                proof.checkSql(engine.expectedCancellation(timeout, attempt.failure), attempt.failure);
                // Server-side wait limits are at least six seconds. An early fail cannot prove the JDBC timer.
                proof.check(attempt.elapsedMillis < 6000 && (!timeout || attempt.elapsedMillis >= 2800));

                proof.stage = Stage.STATEMENT_GONE;
                await(() -> !activeWrite(observer, engine, workerId, scenario.target, 0));
                proof.check(ownedSession(observer, engine, workerId));
                assertRowLocked(observer, scenario.target, engine, proof);
                return attempt.failure;
            } finally {
                // A failed observer never commits or cancels a timeout-path write as a fallback.
                thread.join(TimeUnit.SECONDS.toMillis(8));
                require(!thread.isAlive());
            }
        }
    }

    private static SQLException sessionLoss(Connection observer, Connection worker, long workerId, Engine engine,
                                            int port, String password, Proof proof) throws Exception {
        int marker = proof.scenario.marker;
        proof.stage = Stage.MARKER;
        worker.setAutoCommit(false);
        proof.check(write(worker, marker, UNCOMMITTED_WRITE) == 1);
        proof.check(scalar(worker, READ, marker) == UNCOMMITTED_WRITE);
        proof.check(scalar(observer, READ, marker) == BASELINE);
        assertRowLocked(observer, marker, engine, proof);

        proof.stage = Stage.TERMINATE;
        proof.check(ownedSession(observer, engine, workerId));
        if (engine == Engine.POSTGRESQL) {
            proof.check(scalar(observer,
                    "SELECT CASE WHEN pg_terminate_backend(CAST(? AS integer), 1000) THEN 1 ELSE 0 END",
                    workerId) == 1);
        } else {
            // KILL accepts only a literal. This positive integral ID was obtained from the owned worker.
            execute(observer, "KILL CONNECTION " + workerId);
            proof.check(true);
        }
        proof.stage = Stage.SESSION_GONE;
        await(() -> !ownedSession(observer, engine, workerId));
        proof.check(!ownedSession(observer, engine, workerId));
        SQLException rejected = sqlFailure(() -> scalar(worker, READ, marker));
        proof.checkSql(sqlState(rejected).startsWith("08") || "57P01".equals(sqlState(rejected)), rejected);

        proof.stage = Stage.ROLLBACK;
        proof.check(scalar(observer, READ, marker) == BASELINE);
        proof.check(probeRowLock(observer, marker) == null);

        proof.stage = Stage.FOLLOWUP;
        try (Connection replacement = engine.connect(port, password)) {
            long newId = sessionId(replacement, engine);
            proof.check(newId != workerId && newId != sessionId(observer, engine)
                    && ownedSession(observer, engine, newId));
            replacement.setAutoCommit(false);
            proof.check(write(replacement, marker, RECOVERY_WRITE) == 1);
            replacement.commit();
        }
        proof.check(scalar(observer, READ, marker) == RECOVERY_WRITE);
        return rejected;
    }

    private static void assertRowLocked(Connection observer, int row, Engine engine, Proof proof) throws Exception {
        SQLException blocked = probeRowLock(observer, row);
        boolean expected = engine == Engine.POSTGRESQL ? "55P03".equals(sqlState(blocked))
                : blocked != null && blocked.getErrorCode() == 3572;
        proof.checkSql(expected, blocked);
    }

    private static SQLException probeRowLock(Connection observer, int row) throws Exception {
        // MySQL locking reads require an explicit transaction. Always clear the observer's temporary lock or error.
        observer.setAutoCommit(false);
        try {
            return sqlFailure(() -> scalar(observer, SELECT_FOR_UPDATE, row));
        } finally {
            observer.rollback();
            observer.setAutoCommit(true);
        }
    }

    private static long sessionId(Connection connection, Engine engine) throws Exception {
        long id = scalar(connection, engine == Engine.POSTGRESQL ? "SELECT pg_backend_pid()" : "SELECT CONNECTION_ID()");
        require(id > 0);
        return id;
    }

    private static boolean ownedSession(Connection observer, Engine engine, long id) throws Exception {
        return scalar(observer, engine.sessions, id) == 1;
    }

    private static boolean activeWrite(Connection observer, Engine engine, long workerId, int row, long blockerId)
            throws Exception {
        if (engine == Engine.POSTGRESQL) {
            String query = engine.sessions + " AND state = 'active' AND query = ?";
            String observedUpdate = UPDATE.replaceFirst("\\?", Matcher.quoteReplacement("$1"))
                    .replaceFirst("\\?", Matcher.quoteReplacement("$2"));
            if (blockerId == 0) return scalar(observer, query, workerId, observedUpdate) == 1;
            return scalar(observer, query + " AND wait_event_type = 'Lock' AND ? = ANY(pg_blocking_pids(pid))",
                    workerId, observedUpdate, blockerId) == 1;
        }
        // The isolated provider disables performance_schema and own-account PROCESSLIST is sufficient here.
        // Compare only this owned session's exact fixture SQL. No server query text is returned or logged.
        String observedUpdate = UPDATE.replaceFirst("\\?", Integer.toString(BLOCKED_WRITE))
                .replaceFirst("\\?", Integer.toString(row));
        return scalar(observer, engine.sessions + " AND COMMAND = 'Query' AND BINARY INFO = ?",
                workerId, observedUpdate) == 1;
    }

    private static void await(Condition condition) throws Exception {
        long deadline = System.nanoTime() + TimeUnit.MILLISECONDS.toNanos(POLL_MILLIS);
        do {
            if (condition.test()) return;
            Thread.sleep(POLL_INTERVAL_MILLIS);
        } while (System.nanoTime() < deadline);
        throw new FixtureFailure();
    }

    private static long scalar(Connection connection, String sql, Object... parameters) throws Exception {
        try (PreparedStatement statement = connection.prepareStatement(sql)) {
            statement.setQueryTimeout(STATEMENT_SECONDS);
            for (int index = 0; index < parameters.length; index++) {
                statement.setObject(index + 1, parameters[index]);
            }
            try (ResultSet rows = statement.executeQuery()) {
                require(rows.next());
                long value = rows.getLong(1);
                require(!rows.wasNull() && !rows.next());
                return value;
            }
        }
    }

    private static int write(Connection connection, int row, int value) throws SQLException {
        try (PreparedStatement statement = connection.prepareStatement(UPDATE)) {
            statement.setQueryTimeout(STATEMENT_SECONDS);
            statement.setInt(1, value);
            statement.setInt(2, row);
            return statement.executeUpdate();
        }
    }

    private static void execute(Connection connection, String sql) throws SQLException {
        try (Statement statement = connection.createStatement()) {
            statement.setQueryTimeout(STATEMENT_SECONDS);
            statement.execute(sql);
        }
    }

    private static SQLException sqlFailure(Operation operation) throws Exception {
        try {
            operation.run();
            return null;
        } catch (SQLException failure) {
            return failure;
        }
    }

    private static String sqlState(Throwable failure) {
        if (failure instanceof SQLException sql) {
            String state = sql.getSQLState();
            if (state != null && state.matches("[A-Z0-9]{5}")) return state;
        }
        return "NONE";
    }

    private static String exceptionType(Throwable failure) {
        if (failure == null) return "NONE";
        String type = failure.getClass().getSimpleName();
        return type.matches("[A-Za-z][A-Za-z0-9]{0,63}") ? type : "Exception";
    }

    private static void require(boolean condition) throws FixtureFailure {
        if (!condition) throw new FixtureFailure();
    }

    private enum Engine {
        POSTGRESQL("postgresql", "postgres", "PostgreSQL", "org.postgresql.Driver", "PostgreSQL JDBC Driver",
                17, "42.7.14", "([0-9]+(?:\\.[0-9]+){2})",
                "SELECT COUNT(*) FROM pg_stat_activity WHERE pid = ? AND datname = current_database()"
                        + " AND usename = current_user AND application_name = 'udak-recovery'"),
        MYSQL("mysql", "udak_fixture", "MySQL", "com.mysql.cj.jdbc.Driver", "MySQL Connector/J",
                8, "26.10.0", "mysql-connector-j-([0-9]+(?:\\.[0-9]+){2}) \\(Revision: [A-Za-z0-9._-]{1,128}\\)",
                "SELECT COUNT(*) FROM information_schema.processlist WHERE ID = ? AND DB = DATABASE()"
                        + " AND USER = SUBSTRING_INDEX(USER(), '@', 1)");

        private final String protocol;
        private final String database;
        private final String product;
        private final String driverClass;
        private final String driverName;
        private final int serverMajor;
        private final String expectedDriverVersion;
        private final Pattern driverVersion;
        private final String sessions;

        Engine(String protocol, String database, String product, String driverClass, String driverName,
               int serverMajor, String expectedDriverVersion, String driverVersion, String sessions) {
            this.protocol = protocol;
            this.database = database;
            this.product = product;
            this.driverClass = driverClass;
            this.driverName = driverName;
            this.serverMajor = serverMajor;
            this.expectedDriverVersion = expectedDriverVersion;
            this.driverVersion = Pattern.compile(driverVersion);
            this.sessions = sessions;
        }

        Connection connect(int port, String password) throws SQLException, FixtureFailure {
            String url = "jdbc:" + protocol + "://127.0.0.1:" + port + "/" + database;
            require(DriverManager.getDriver(url).getClass().getName().equals(driverClass));
            Properties properties = new Properties();
            properties.setProperty("user", "udak_fixture");
            properties.setProperty("password", password);
            if (this == POSTGRESQL) {
                properties.setProperty("ApplicationName", "udak-recovery");
                properties.setProperty("currentSchema", "public");
                properties.setProperty("sslmode", "disable");
                properties.setProperty("gssEncMode", "disable");
                properties.setProperty("connectTimeout", "2");
                properties.setProperty("cancelSignalTimeout", "2");
                properties.setProperty("socketTimeout", "8");
                properties.setProperty("options", "-c statement_timeout=6500 -c lock_timeout=6000");
            } else {
                properties.setProperty("connectTimeout", "2000");
                properties.setProperty("socketTimeout", "8000");
                properties.setProperty("sslMode", "DISABLED");
                properties.setProperty("logger", "com.mysql.cj.log.NullLogger");
                properties.setProperty("autoReconnect", "false");
                properties.setProperty("enableQueryTimeouts", "true");
                properties.setProperty("queryTimeoutKillsConnection", "false");
                properties.setProperty("useServerPrepStmts", "false");
                properties.setProperty("sessionVariables",
                        "max_execution_time=0,lock_wait_timeout=7,innodb_lock_wait_timeout=7");
            }
            try {
                return DriverManager.getConnection(url, properties);
            } finally {
                properties.remove("password");
            }
        }

        String verifiedVersion(Connection connection) throws SQLException, FixtureFailure {
            DatabaseMetaData metadata = connection.getMetaData();
            require(database.equals(connection.getCatalog()));
            require(this != POSTGRESQL || "public".equals(connection.getSchema()));
            require(product.equalsIgnoreCase(metadata.getDatabaseProductName()));
            require(driverName.equalsIgnoreCase(metadata.getDriverName()));
            String server = extractVersion(SERVER_VERSION, metadata.getDatabaseProductVersion());
            String driver = extractVersion(driverVersion, metadata.getDriverVersion());
            String[] parts = server.split("\\.");
            require(Integer.parseInt(parts[0]) == serverMajor && metadata.getDatabaseMajorVersion() == serverMajor);
            require(Integer.parseInt(parts[1]) == metadata.getDatabaseMinorVersion());
            require(this != MYSQL || "0".equals(parts[1]));
            require(expectedDriverVersion.equals(driver));
            return server;
        }

        boolean expectedCancellation(boolean timeout, SQLException failure) {
            if (this == POSTGRESQL) return "57014".equals(sqlState(failure));
            String expectedType = timeout ? "MySQLTimeoutException" : "MySQLStatementCancelledException";
            return expectedType.equals(exceptionType(failure)) || "70100".equals(sqlState(failure));
        }
    }

    private static String extractVersion(Pattern format, String release) throws FixtureFailure {
        require(release != null && release.length() <= 256);
        Matcher match = format.matcher(release);
        require(match.matches());
        return match.group(1);
    }

    private enum Scenario {
        JDBC_CANCEL(1, 2), JDBC_TIMEOUT(3, 4), SESSION_LOSS(5, 6);

        private final int target;
        private final int marker;

        Scenario(int target, int marker) {
            this.target = target;
            this.marker = marker;
        }
    }

    private enum Stage {
        ARGUMENTS, INPUT, CONNECT, IDENTITY, FIXTURE, BLOCKER, MARKER, BLOCKED, TRIGGER, STATEMENT_GONE,
        TRANSACTION, TERMINATE, SESSION_GONE, ROLLBACK, FOLLOWUP, CLOSE
    }

    private static final class Proof {
        private Scenario scenario;
        private Stage stage = Stage.ARGUMENTS;
        private int assertions;

        void begin(Scenario next) {
            scenario = next;
            stage = Stage.CONNECT;
            assertions = 0;
        }

        void check(boolean condition) throws FixtureFailure {
            require(condition);
            assertions++;
        }

        void checkSql(boolean condition, SQLException failure) throws SQLException, FixtureFailure {
            if (!condition && failure != null) throw failure;
            check(condition);
        }

        String result(Engine engine, SQLException trigger) {
            boolean sessionLoss = scenario == Scenario.SESSION_LOSS;
            String state = sessionLoss ? "DISCONNECTED" : engine == Engine.POSTGRESQL ? "ABORTED" : "ACTIVE";
            return "RECOVERY_RESULT profile=" + engine + " scenario=" + scenario + " status=PASS sqlstate="
                    + sqlState(trigger) + " exception=" + exceptionType(trigger) + " blocked_observed=" + !sessionLoss
                    + " statement_gone_while_blocked=" + !sessionLoss + " failed_write_absent=true transaction_state="
                    + state + " rollback_verified=true session_reused=" + !sessionLoss
                    + " new_session_verified=" + sessionLoss + " followup_committed=true assertions=" + assertions;
        }
    }

    @FunctionalInterface
    private interface Condition {
        boolean test() throws Exception;
    }

    @FunctionalInterface
    private interface Operation {
        long run() throws Exception;
    }

    private record Attempt(SQLException failure, long elapsedMillis) {}

    private static final class FixtureFailure extends Exception {
        private static final long serialVersionUID = 1L;
    }
}
