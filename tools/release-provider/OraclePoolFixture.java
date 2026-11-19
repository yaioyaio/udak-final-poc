import com.zaxxer.hikari.HikariConfig;
import com.zaxxer.hikari.HikariDataSource;
import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.io.PrintStream;
import java.nio.charset.StandardCharsets;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.Statement;
import java.util.Properties;
import java.util.logging.LogManager;

/** Functional test scoped to one new Oracle Free PDB schema. */
public final class OraclePoolFixture {
    private static void require(boolean condition) {
        if (!condition) throw new IllegalStateException();
    }

    private static String scalar(Connection connection, String sql) throws Exception {
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

    private static String session(Connection connection) throws Exception {
        String id = scalar(connection, "select sys_context('USERENV','SESSIONID') from dual");
        require(id != null && id.matches("[1-9][0-9]{0,19}"));
        return id;
    }

    private static void insert(Connection connection, int id) throws Exception {
        try (PreparedStatement statement = connection.prepareStatement("insert into g5_pool (id) values (?)")) {
            statement.setQueryTimeout(5);
            statement.setInt(1, id);
            require(statement.executeUpdate() == 1);
        }
    }

    private static String execute() throws Exception {
        BufferedReader input = new BufferedReader(new InputStreamReader(System.in, StandardCharsets.US_ASCII));
        String port = input.readLine();
        String schema = input.readLine();
        String secret = input.readLine();
        require(port.matches("[0-9]{1,5}") && Integer.parseInt(port) > 0 && Integer.parseInt(port) <= 65535);
        require(schema.matches("UDAKG5[A-F0-9]{24}") && secret.matches("ABab12#_[A-Fa-f0-9]{22}") && input.readLine() == null);
        String url = "jdbc:oracle:thin:@//127.0.0.1:" + port + "/FREEPDB1";
        Properties properties = new Properties();
        properties.setProperty("user", schema);
        properties.setProperty("password", secret);
        properties.setProperty("oracle.net.CONNECT_TIMEOUT", "3000");
        properties.setProperty("oracle.jdbc.ReadTimeout", "5000");
        HikariConfig config = new HikariConfig();
        config.setJdbcUrl(url);
        config.setDataSourceProperties(properties);
        config.setMaximumPoolSize(1);
        config.setMinimumIdle(0);
        config.setConnectionTimeout(5000);
        config.setValidationTimeout(2000);
        config.setInitializationFailTimeout(-1);
        try (Connection observer = DriverManager.getConnection(url, properties);
             HikariDataSource pool = new HikariDataSource(config)) {
            require("Oracle".equals(observer.getMetaData().getDatabaseProductName()));
            require("23.26.4.0.0".equals(observer.getMetaData().getDriverVersion()));
            require("FREEPDB1".equals(scalar(observer, "select sys_context('USERENV','CON_NAME') from dual")));
            require(schema.equals(scalar(observer, "select sys_context('USERENV','CURRENT_SCHEMA') from dual")));
            String version = scalar(observer, "select version_full from product_component_version where product like 'Oracle%'");
            require(version != null && version.matches("23\\.26(\\.[0-9]{1,3}){3}"));
            try (Statement statement = observer.createStatement()) {
                statement.setQueryTimeout(5);
                statement.execute("create table g5_pool (id number(9) not null)");
            }
            String original;
            try (Connection first = pool.getConnection()) {
                original = session(first);
                require(!original.equals(session(observer)));
                first.setAutoCommit(false);
                insert(first, 1);
            }
            require("0".equals(scalar(observer, "select count(*) from g5_pool")));
            try (Connection next = pool.getConnection()) {
                require(next.getAutoCommit() && original.equals(session(next)));
                next.setAutoCommit(false);
                insert(next, 2);
                next.commit();
            }
            require("2".equals(scalar(observer, "select id from g5_pool")));
            return version;
        }
    }

    public static void main(String[] args) {
        PrintStream protocol = System.out;
        System.setOut(new PrintStream(OutputStream.nullOutputStream()));
        System.setErr(new PrintStream(OutputStream.nullOutputStream()));
        LogManager.getLogManager().reset();
        try {
            protocol.println("ORACLE_POOL_PASS " + execute());
        } catch (Throwable failure) {
            protocol.println("ORACLE_POOL_FAIL");
            System.exit(1);
        }
    }
}
