import com.zaxxer.hikari.HikariConfig;
import com.zaxxer.hikari.HikariDataSource;
import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.io.PrintStream;
import java.nio.charset.StandardCharsets;
import java.sql.Connection;
import java.sql.DatabaseMetaData;
import java.sql.DriverManager;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.SQLRecoverableException;
import java.sql.Statement;
import java.util.Properties;
import java.util.concurrent.Callable;
import java.util.concurrent.FutureTask;
import java.util.concurrent.TimeUnit;
import java.util.logging.LogManager;

/** One local PDB schema, one blocked write at a time, one pre-commit disconnect. */
public final class OracleRecoveryFixture {
    private static final String PIN = "23.26.4.0.0";
    private static final String CONTEXT = "username = sys_context('USERENV','SESSION_USER') "
            + "and con_id = to_number(sys_context('USERENV','CON_ID')) ";
    private static final String UPDATE = "update g5_recovery set marker = ? where id = ?";
    private static final String INSERT = "insert into g5_recovery (id, marker) values (?, ?)";
    private static final String READ_BASE = "select marker from g5_recovery where id = 1";
    private static final int TIMEOUT_SECONDS = 4;

    private record Session(int sid, int serial) {}

    private static void require(boolean condition) {
        if (!condition) throw new IllegalStateException();
    }

    private static void emit(PrintStream protocol, String line) {
        protocol.println(line);
        protocol.flush();
    }

    private static <T> FutureTask<T> start(Callable<T> action) {
        FutureTask<T> task = new FutureTask<>(action);
        Thread thread = new Thread(task, "oracle-fixture-worker");
        thread.setDaemon(true);
        thread.start();
        return task;
    }

    private static String scalar(Connection connection, String sql) throws SQLException {
        try (Statement statement = connection.createStatement()) {
            statement.setQueryTimeout(5);
            try (ResultSet rows = statement.executeQuery(sql)) {
                require(rows.next());
                String value = rows.getString(1);
                require(!rows.next());
                return value;
            }
        }
    }

    private static Session session(Connection connection) throws SQLException {
        String sql = "select sid, serial# from sys.v_$session where " + CONTEXT
                + "and sid = to_number(sys_context('USERENV','SID'))";
        try (Statement statement = connection.createStatement()) {
            statement.setQueryTimeout(5);
            try (ResultSet rows = statement.executeQuery(sql)) {
                require(rows.next());
                Session session = new Session(rows.getInt(1), rows.getInt(2));
                require(session.sid() > 0 && session.serial() > 0 && !rows.next());
                return session;
            }
        }
    }

    private static void write(Connection connection, String sql, int first, int second) throws SQLException {
        try (PreparedStatement statement = connection.prepareStatement(sql)) {
            statement.setQueryTimeout(5);
            statement.setInt(1, first);
            statement.setInt(2, second);
            require(statement.executeUpdate() == 1);
        }
    }

    private static void awaitBlocked(Connection blocker, Session worker, FutureTask<?> task) throws Exception {
        String sql = "select count(*) from sys.v_$session where " + CONTEXT
                + "and sid = ? and serial# = ? and status = 'ACTIVE' and state = 'WAITING' "
                + "and blocking_session_status = 'VALID' "
                + "and blocking_session = to_number(sys_context('USERENV','SID'))";
        try (PreparedStatement probe = blocker.prepareStatement(sql)) {
            probe.setQueryTimeout(2);
            probe.setInt(1, worker.sid());
            probe.setInt(2, worker.serial());
            long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(4);
            do {
                require(!task.isDone());
                try (ResultSet rows = probe.executeQuery()) {
                    require(rows.next());
                    if (rows.getInt(1) == 1) return;
                }
                Thread.sleep(100);
            } while (System.nanoTime() < deadline);
            throw new IllegalStateException();
        }
    }

    private static void blockedUpdate(Connection blocker, Connection worker, boolean useTimeout) throws Exception {
        Session target = session(worker);
        write(blocker, UPDATE, 11, 1);
        try (PreparedStatement update = worker.prepareStatement(UPDATE)) {
            update.setQueryTimeout(useTimeout ? TIMEOUT_SECONDS : 0);
            update.setInt(1, 99);
            update.setInt(2, 1);
            FutureTask<SQLException> task = start(() -> {
                try {
                    update.executeUpdate();
                    return null;
                } catch (SQLException error) {
                    return error;
                }
            });
            try {
                awaitBlocked(blocker, target, task);
                if (!useTimeout) update.cancel();
                SQLException error = task.get(9, TimeUnit.SECONDS);
                require(error != null && error.getErrorCode() == 1013);
                // Check the writer's own view before rollback could hide an accidental update.
                require("10".equals(scalar(worker, READ_BASE)));
            } finally {
                blocker.rollback();
            }
        }
        worker.rollback();
        require("10".equals(scalar(blocker, READ_BASE)));
    }

    private static void requireDisconnected(Connection doomed) throws SQLException {
        try {
            scalar(doomed, "select 1 from dual");
        } catch (SQLException error) {
            String state = error.getSQLState();
            require(error instanceof SQLRecoverableException || (state != null && state.startsWith("08"))
                    || error.getErrorCode() == 28 || error.getErrorCode() == 3113
                    || error.getErrorCode() == 3114);
            return;
        }
        throw new IllegalStateException();
    }

    private static void replacement(Connection observer, HikariDataSource pool, BufferedReader input,
                                    PrintStream protocol) throws Exception {
        Session original;
        try (Connection doomed = pool.getConnection()) {
            original = session(doomed);
            require(!original.equals(session(observer)));
            doomed.setAutoCommit(false);
            write(doomed, INSERT, 2, 20);
            require("1".equals(scalar(doomed, "select count(*) from g5_recovery where id = 2")));
            require("0".equals(scalar(observer, "select count(*) from g5_recovery where id = 2")));
            emit(protocol, "ORACLE_DISCONNECT_READY " + original.sid() + " " + original.serial());
            require("DISCONNECTED".equals(start(input::readLine).get(25, TimeUnit.SECONDS)));
            requireDisconnected(doomed);
        }
        // Re-borrow from the same one-slot pool after it handles the broken physical connection.
        try (Connection fresh = pool.getConnection()) {
            require(fresh.getAutoCommit() && !original.equals(session(fresh)));
            fresh.setAutoCommit(false);
            require("10".equals(scalar(fresh, READ_BASE)));
            write(fresh, INSERT, 2, 22); // the original transaction released this unique key
            fresh.rollback();
            write(fresh, INSERT, 3, 30);
            fresh.commit();
        }
        require("10".equals(scalar(observer, READ_BASE)));
        require("0".equals(scalar(observer, "select count(*) from g5_recovery where id = 2")));
        require("30".equals(scalar(observer, "select marker from g5_recovery where id = 3")));
        require("2".equals(scalar(observer, "select count(*) from g5_recovery")));
    }

    private static void execute(PrintStream protocol) throws Exception {
        BufferedReader input = new BufferedReader(new InputStreamReader(System.in, StandardCharsets.US_ASCII));
        String port = input.readLine();
        String schema = input.readLine();
        String secret = input.readLine();
        require(port.matches("[0-9]{1,5}") && Integer.parseInt(port) > 0 && Integer.parseInt(port) <= 65535);
        require(schema.matches("UDAKG5[A-F0-9]{24}") && secret.matches("ABab12#_[A-Fa-f0-9]{22}"));
        String url = "jdbc:oracle:thin:@//127.0.0.1:" + port + "/FREEPDB1";
        Properties properties = new Properties();
        properties.setProperty("user", schema);
        properties.setProperty("password", secret);
        properties.setProperty("oracle.net.CONNECT_TIMEOUT", "3000");
        properties.setProperty("oracle.jdbc.ReadTimeout", "12000");
        try (Connection observer = DriverManager.getConnection(url, properties)) {
            DatabaseMetaData metadata = observer.getMetaData();
            require("Oracle".equals(metadata.getDatabaseProductName()) && PIN.equals(metadata.getDriverVersion()));
            require("Oracle JDBC driver".equalsIgnoreCase(metadata.getDriverName()));
            require(PIN.equals(scalar(observer, "select version_full from product_component_version where product like 'Oracle%'")));
            require("FREEPDB1".equals(scalar(observer, "select sys_context('USERENV','CON_NAME') from dual")));
            require(schema.equals(scalar(observer, "select sys_context('USERENV','SESSION_USER') from dual")));
            require(schema.equals(scalar(observer, "select sys_context('USERENV','CURRENT_SCHEMA') from dual")));
            try (Statement statement = observer.createStatement()) {
                statement.setQueryTimeout(5);
                statement.execute("create table g5_recovery (id number(9) not null, marker number(9) not null, "
                        + "constraint g5_recovery_pk primary key (id))");
            }
            observer.setAutoCommit(false);
            write(observer, INSERT, 1, 10);
            observer.commit();
            try (Connection worker = DriverManager.getConnection(url, properties)) {
                worker.setAutoCommit(false);
                blockedUpdate(observer, worker, false);
                emit(protocol, "ORACLE_CANCEL PASS");
                blockedUpdate(observer, worker, true);
                emit(protocol, "ORACLE_TIMEOUT PASS");
            }
            HikariConfig config = new HikariConfig();
            config.setJdbcUrl(url);
            config.setDataSourceProperties(properties);
            config.setMaximumPoolSize(1);
            config.setMinimumIdle(0);
            config.setConnectionTimeout(5000);
            config.setValidationTimeout(2000);
            config.setInitializationFailTimeout(-1);
            try (HikariDataSource pool = new HikariDataSource(config)) {
                replacement(observer, pool, input, protocol);
            }
        }
        emit(protocol, "ORACLE_REPLACEMENT PASS");
    }

    public static void main(String[] args) {
        PrintStream protocol = System.out;
        System.setOut(new PrintStream(OutputStream.nullOutputStream()));
        System.setErr(new PrintStream(OutputStream.nullOutputStream()));
        LogManager.getLogManager().reset();
        try {
            execute(protocol);
        } catch (Throwable error) {
            emit(protocol, "ORACLE_RECOVERY_FAIL");
            System.exit(1);
        }
    }
}
