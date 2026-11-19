import com.zaxxer.hikari.HikariConfig;
import com.zaxxer.hikari.HikariDataSource;

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
import java.util.logging.LogManager;
import java.util.regex.Pattern;

/** Single-borrower, pre-commit failure fixture on a freshly owned native database. */
public final class PoolFixture {
    private enum Engine {
        POSTGRESQL("postgresql", "postgres", "17.11", "42.7.14",
                "SELECT pg_backend_pid()",
                "SELECT COUNT(*) FROM pg_stat_activity WHERE pid=? AND datname=current_database()"
                        + " AND usename=current_user AND application_name='udak-pool'",
                "SELECT CASE WHEN current_setting('transaction_isolation')='read committed' THEN 1 ELSE 0 END"),
        MYSQL("mysql", "udak_fixture", "8.0.46", "26.10.0",
                "SELECT CONNECTION_ID()",
                "SELECT COUNT(*) FROM information_schema.processlist WHERE ID=? AND DB=DATABASE()"
                        + " AND USER=SUBSTRING_INDEX(USER(),'@',1)",
                "SELECT CASE WHEN @@SESSION.transaction_isolation='READ-COMMITTED' THEN 1 ELSE 0 END");

        final String protocol, database, server, driver, sessionId, owned, isolation;

        Engine(String protocol, String database, String server, String driver, String sessionId,
               String owned, String isolation) {
            this.protocol = protocol;
            this.database = database;
            this.server = server;
            this.driver = driver;
            this.sessionId = sessionId;
            this.owned = owned;
            this.isolation = isolation;
        }

        Properties options(String password) {
            Properties p = new Properties();
            p.setProperty("user", "udak_fixture");
            p.setProperty("password", password);
            if (this == POSTGRESQL) {
                p.setProperty("ApplicationName", "udak-pool");
                p.setProperty("sslmode", "disable");
                p.setProperty("gssEncMode", "disable");
                p.setProperty("connectTimeout", "2");
                p.setProperty("socketTimeout", "5");
                p.setProperty("options", "-c statement_timeout=3000 -c lock_timeout=2000");
            } else {
                p.setProperty("sslMode", "DISABLED");
                p.setProperty("logger", "com.mysql.cj.log.NullLogger");
                p.setProperty("connectTimeout", "2000");
                p.setProperty("socketTimeout", "5000");
                p.setProperty("autoReconnect", "false");
                p.setProperty("autoReconnectForPools", "false");
                p.setProperty("sessionVariables", "max_execution_time=3000,innodb_lock_wait_timeout=2");
            }
            return p;
        }

        void verifyMetadata(Connection connection) throws SQLException {
            DatabaseMetaData meta = connection.getMetaData();
            require(database.equals(connection.getCatalog()));
            require((this == POSTGRESQL ? "PostgreSQL" : "MySQL").equals(meta.getDatabaseProductName()));
            require(meta.getDatabaseProductVersion().matches(Pattern.quote(server) + "(?:[ -][ -~]{1,180})?"));
            String driverPattern = this == POSTGRESQL ? Pattern.quote(driver)
                    : "mysql-connector-j-" + Pattern.quote(driver) + " \\(Revision: [a-zA-Z0-9._-]{1,128}\\)";
            require(meta.getDriverVersion().matches(driverPattern));
        }
    }

    private static String stage = "INPUT";

    private static void require(boolean condition) {
        if (!condition) throw new IllegalStateException();
    }

    private static long number(Connection connection, String sql, long... values) throws SQLException {
        try (PreparedStatement statement = connection.prepareStatement(sql)) {
            for (int i = 0; i < values.length; i++) statement.setLong(i + 1, values[i]);
            try (ResultSet rows = statement.executeQuery()) {
                require(rows.next());
                long number = rows.getLong(1);
                require(!rows.wasNull() && !rows.next());
                return number;
            }
        }
    }

    private static void execute(Connection connection, String sql) throws SQLException {
        try (Statement statement = connection.createStatement()) {
            statement.execute(sql);
        }
    }

    private static long count(Connection connection, int id) throws SQLException {
        return number(connection, "SELECT COUNT(*) FROM udak_pool_fixture WHERE id=?", id);
    }

    private static void insert(Connection connection, int id) throws SQLException {
        try (PreparedStatement statement = connection.prepareStatement("INSERT INTO udak_pool_fixture(id) VALUES (?)")) {
            statement.setInt(1, id);
            require(statement.executeUpdate() == 1);
        }
    }

    private static HikariDataSource pool(String url, Properties options) {
        HikariConfig config = new HikariConfig();
        config.setPoolName("udak-pool-fixture");
        config.setJdbcUrl(url);
        config.setDataSourceProperties(options);
        config.setMaximumPoolSize(1);
        config.setMinimumIdle(0);
        config.setConnectionTimeout(3000);
        config.setValidationTimeout(1500);
        config.setInitializationFailTimeout(-1);
        config.setAutoCommit(true);
        config.setTransactionIsolation("TRANSACTION_READ_COMMITTED");
        return new HikariDataSource(config);
    }

    private static long cleanReuse(Engine engine, Connection observer, HikariDataSource pool) throws SQLException {
        long id;
        try (Connection worker = pool.getConnection()) {
            engine.verifyMetadata(worker);
            id = number(worker, engine.sessionId);
            require(id > 0 && id != number(observer, engine.sessionId) && number(observer, engine.owned, id) == 1);
            require(worker.getAutoCommit() && number(worker, engine.isolation) == 1);
            worker.setTransactionIsolation(Connection.TRANSACTION_SERIALIZABLE);
            worker.setAutoCommit(false);
            insert(worker, 1);
            require(count(worker, 1) == 1 && count(observer, 1) == 0);
        }
        try (Connection next = pool.getConnection()) {
            require(number(next, engine.sessionId) == id);
            require(next.getAutoCommit() && next.getTransactionIsolation() == Connection.TRANSACTION_READ_COMMITTED);
            require(number(next, engine.isolation) == 1 && count(next, 1) == 0);
            next.setAutoCommit(false);
            insert(next, 2);
            next.commit();
        }
        require(count(observer, 1) == 0 && count(observer, 2) == 1);
        return id;
    }

    private static void replace(Engine engine, Connection observer, HikariDataSource pool, long oldId)
            throws SQLException {
        try (Connection worker = pool.getConnection()) {
            require(number(worker, engine.sessionId) == oldId);
            worker.setAutoCommit(false);
            insert(worker, 3);
            require(count(worker, 3) == 1 && count(observer, 3) == 0);
            stage = "TERMINATE_OWNED";
            require(oldId > 0 && oldId != number(observer, engine.sessionId) && number(observer, engine.owned, oldId) == 1);
            if (engine == Engine.POSTGRESQL) {
                require(number(observer, "SELECT CASE WHEN pg_terminate_backend(CAST(? AS integer), 1000)"
                        + " THEN 1 ELSE 0 END", oldId) == 1);
            } else {
                // KILL accepts a literal. Only the still-borrowed worker's verified positive server ID reaches here.
                execute(observer, "KILL CONNECTION " + oldId);
            }
            stage = "BROKEN_CONNECTION";
            try {
                number(worker, "SELECT 1");
                throw new IllegalStateException();
            } catch (SQLException expected) {
                String state = expected.getSQLState();
                require(state != null && (state.startsWith("08") || (engine == Engine.POSTGRESQL && state.equals("57P01"))));
            }
        }
        stage = "REPLACEMENT";
        try (Connection next = pool.getConnection()) {
            long newId = number(next, engine.sessionId);
            require(newId > 0 && newId != oldId && newId != number(observer, engine.sessionId));
            require(number(observer, engine.owned, oldId) == 0 && number(observer, engine.owned, newId) == 1);
            require(next.getAutoCommit() && number(next, engine.isolation) == 1 && count(next, 3) == 0);
            next.setAutoCommit(false);
            insert(next, 4);
            next.commit();
        }
        require(count(observer, 1) == 0 && count(observer, 2) == 1
                && count(observer, 3) == 0 && count(observer, 4) == 1);
    }

    public static void main(String[] args) {
        PrintStream report = System.out;
        PrintStream discard = new PrintStream(OutputStream.nullOutputStream());
        System.setOut(discard);
        System.setErr(discard);
        LogManager.getLogManager().reset();
        try {
            require(args.length == 2 && args[1].matches("[1-9][0-9]{0,4}") && Integer.parseInt(args[1]) <= 65535);
            Engine engine = Engine.valueOf(args[0]);
            byte[] bytes = System.in.readNBytes(50);
            require(bytes.length == 49 && bytes[48] == '\n');
            String password = new String(bytes, 0, 48, StandardCharsets.US_ASCII);
            Arrays.fill(bytes, (byte) 0);
            require(password.matches("[a-f0-9]{48}"));
            String url = "jdbc:" + engine.protocol + "://127.0.0.1:" + args[1] + "/" + engine.database;
            Properties options = engine.options(password);
            DriverManager.setLoginTimeout(2);
            stage = "SETUP";
            try (Connection observer = DriverManager.getConnection(url, options);
                 HikariDataSource pool = pool(url, options)) {
                engine.verifyMetadata(observer);
                execute(observer, "CREATE TABLE udak_pool_fixture (id INTEGER PRIMARY KEY)"
                        + (engine == Engine.MYSQL ? " ENGINE=InnoDB" : ""));
                stage = "ROLLBACK_RESET_REUSE";
                long oldId = cleanReuse(engine, observer, pool);
                stage = "PRECOMMIT_LOSS";
                replace(engine, observer, pool, oldId);
                stage = "CLEANUP";
                execute(observer, "DROP TABLE udak_pool_fixture");
            } finally {
                options.remove("password");
            }
            report.println("POOL PASS " + engine + " " + engine.server + " " + engine.driver);
            report.println("ROLLBACK_RESET_REUSE PASS");
            report.println("PRECOMMIT_REPLACEMENT PASS");
        } catch (Exception | LinkageError error) {
            report.println("POOL FAIL " + stage);
            System.exit(1);
        }
    }
}
