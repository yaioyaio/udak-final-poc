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

public final class RestartFixture {
    private static void require(boolean condition) {
        if (!condition) throw new IllegalStateException();
    }

    private static void write(Connection connection, int id) throws SQLException {
        try (PreparedStatement insert = connection.prepareStatement("INSERT INTO udak_restart_fixture(id) VALUES (?)")) {
            insert.setInt(1, id);
            require(insert.executeUpdate() == 1);
        }
    }

    private static int count(Connection connection, int id) throws SQLException {
        try (PreparedStatement select = connection.prepareStatement("SELECT COUNT(*) FROM udak_restart_fixture WHERE id=?")) {
            select.setInt(1, id);
            try (ResultSet rows = select.executeQuery()) {
                require(rows.next());
                int count = rows.getInt(1);
                require(!rows.wasNull() && !rows.next());
                return count;
            }
        }
    }

    private static void seed(Connection connection, boolean postgres) throws SQLException {
        try (Statement setup = connection.createStatement()) {
            setup.execute("CREATE TABLE udak_restart_fixture(id INTEGER PRIMARY KEY)" + (postgres ? "" : " ENGINE=InnoDB"));
        }
        connection.setAutoCommit(false);
        write(connection, 1);
        connection.commit();
        write(connection, 2);
        require(count(connection, 2) == 1);
        connection.rollback();
        require(count(connection, 1) == 1 && count(connection, 2) == 0);
        connection.rollback();
    }

    private static void verify(Connection connection) throws SQLException {
        require(count(connection, 1) == 1 && count(connection, 2) == 0 && count(connection, 3) == 0);
        connection.setAutoCommit(false);
        write(connection, 3);
        connection.commit();
    }

    public static void main(String[] args) {
        PrintStream report = System.out;
        PrintStream discard = new PrintStream(OutputStream.nullOutputStream());
        System.setOut(discard);
        System.setErr(discard);
        LogManager.getLogManager().reset();
        try {
            require(args.length == 3 && args[1].matches("[1-9][0-9]{0,4}") && Integer.parseInt(args[1]) <= 65535);
            boolean postgres = "POSTGRESQL".equals(args[0]);
            require(postgres || "MYSQL".equals(args[0]));
            boolean before = "SEED".equals(args[2]);
            require(before || "VERIFY".equals(args[2]));
            byte[] bytes = System.in.readNBytes(50);
            require(bytes.length == 49 && bytes[48] == '\n');
            String password = new String(bytes, 0, 48, StandardCharsets.US_ASCII);
            Arrays.fill(bytes, (byte) 0);
            require(password.matches("[0-9a-f]{48}"));
            String db = postgres ? "postgres" : "udak_fixture";
            String url = "jdbc:" + (postgres ? "postgresql" : "mysql") + "://127.0.0.1:" + args[1] + "/" + db;
            Properties options = new Properties();
            options.setProperty("user", "udak_fixture");
            options.setProperty("password", password);
            options.setProperty("connectTimeout", postgres ? "2" : "2000");
            options.setProperty("socketTimeout", postgres ? "5" : "5000");
            if (postgres) {
                options.setProperty("sslmode", "disable");
                options.setProperty("gssEncMode", "disable");
                options.setProperty("options", "-c statement_timeout=3000 -c lock_timeout=2000");
            } else {
                options.setProperty("sslMode", "DISABLED");
                options.setProperty("logger", "com.mysql.cj.log.NullLogger");
                options.setProperty("autoReconnect", "false");
            }
            DriverManager.setLoginTimeout(2);
            try {
                try (Connection connection = DriverManager.getConnection(url, options)) {
                    DatabaseMetaData meta = connection.getMetaData();
                    require(db.equals(connection.getCatalog()) && connection.getAutoCommit());
                    require((postgres ? "PostgreSQL" : "MySQL").equals(meta.getDatabaseProductName()));
                    require(meta.getDatabaseProductVersion().matches(
                            (postgres ? "17\\.11" : "8\\.0\\.46") + "(?:[ -][ -~]{1,180})?"));
                    require(meta.getDriverVersion().matches(postgres ? "42\\.7\\.14"
                            : "mysql-connector-j-26\\.10\\.0 \\(Revision: [A-Za-z0-9._-]{1,128}\\)"));
                    if (before) seed(connection, postgres);
                    else verify(connection);
                }
                if (!before) {
                    try (Connection observer = DriverManager.getConnection(url, options);
                         Statement cleanup = observer.createStatement()) {
                        require(count(observer, 1) == 1 && count(observer, 2) == 0 && count(observer, 3) == 1);
                        cleanup.execute("DROP TABLE udak_restart_fixture");
                    }
                }
            } finally {
                options.remove("password");
            }
            report.println("RESTART " + args[0] + " " + args[2] + " PASS");
        } catch (Exception | LinkageError failure) {
            report.println("RESTART FAIL");
            System.exit(1);
        }
    }
}
