package dev.udak.testkit;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.DataOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.PrintWriter;
import java.lang.reflect.Proxy;
import java.sql.Connection;
import java.sql.Driver;
import java.sql.DriverManager;
import java.sql.DriverPropertyInfo;
import java.sql.SQLException;
import java.sql.SQLFeatureNotSupportedException;
import java.util.Arrays;
import java.util.EnumMap;
import java.util.Map;
import java.util.Properties;
import java.util.ServiceLoader;
import java.util.logging.Logger;
import javax.sql.DataSource;

/** Exercises the pipe and JDBC options with synthetic values and a driver that never opens a socket. */
public final class DedicatedRuntimeProviderTest {
    private static final String GATE = "udak.g2.dedicatedPipe";
    private static final int MAGIC = 0x5544414B;
    private static final String DATABASE = "synthetic_schema";
    private static final String USER = "synthetic_user";
    private static final String PASSWORD = "synthetic_password_012345-ABC";
    private static final String OWNERSHIP = "0123456789abcdef0123456789abcdef";
    private static final String INVALID_PIPE = "Invalid dedicated database pipe";
    private static final String LOGGING_DISABLED = "Dedicated database logging is disabled";
    private static int assertions;

    private DedicatedRuntimeProviderTest() { }

    public static void main(String[] args) throws Exception {
        testGateAndSharedParse();
        testInvalidFrames();
        testDataSources();
        System.out.println("DEDICATED DATABASE PROVIDER: PASS (assertions=" + assertions + ")");
    }

    private static void testGateAndSharedParse() throws Exception {
        var input = new CountingInput(frame(row("POSTGRESQL", 15432)));
        InputStream originalInput = System.in;
        String originalGate = System.getProperty(GATE);
        try {
            System.setIn(input);
            System.clearProperty(GATE);
            var providers = new EnumMap<DatabaseProfile, RealDatabaseProvider>(DatabaseProfile.class);
            for (RealDatabaseProvider provider : ServiceLoader.load(RealDatabaseProvider.class)) {
                if (provider instanceof DedicatedRuntimeProvider) {
                    check(providers.put(provider.profile(), provider) == null);
                    check(!provider.dedicatedSchemaApproved());
                }
            }
            check(providers.size() == 4 && input.calls == 0);
            RealDatabaseProvider postgres = providers.get(DatabaseProfile.POSTGRESQL);
            System.setProperty(GATE, "TRUE");
            check(!postgres.dedicatedSchemaApproved() && input.calls == 0);
            expectFailure(IllegalStateException.class, "Dedicated database provider is not approved", postgres::dataSource);
            check(input.calls == 0);

            System.setProperty(GATE, "true");
            check(postgres.profile() == DatabaseProfile.POSTGRESQL && input.calls == 0);
            RealDatabaseProvider mysql = providers.get(DatabaseProfile.MYSQL);
            check(!mysql.dedicatedSchemaApproved() && input.calls > 0);
            int calls = input.calls;
            expectFailure(IllegalStateException.class, "Dedicated database provider is not approved", mysql::dataSource);
            check(postgres.dedicatedSchemaApproved());
            check(postgres.dataSource() == new DedicatedRuntimeProvider.Postgresql().dataSource());
            check(!providers.get(DatabaseProfile.SQLSERVER).dedicatedSchemaApproved());
            check(!providers.get(DatabaseProfile.ORACLE).dedicatedSchemaApproved());
            System.clearProperty(GATE);
            check(!postgres.dedicatedSchemaApproved() && input.calls == calls);
        } finally {
            System.setIn(originalInput);
            if (originalGate == null) System.clearProperty(GATE);
            else System.setProperty(GATE, originalGate);
        }
    }

    private static void testInvalidFrames() throws Exception {
        Row valid = row("POSTGRESQL", 15432);
        byte[] one = frame(valid);
        reject(frame(0, 1, 1, valid));
        reject(frame(MAGIC, 2, 1, valid));
        reject(frame(MAGIC, 1, 0));
        reject(frame(MAGIC, 1, 5));
        reject(frame(valid, valid));
        reject(frame(row("SYNTHETIC", 15432)));
        reject(frame(row("POSTGRESQL", 0)));
        reject(frame(row("POSTGRESQL", 65536)));
        reject(frame(new Row("POSTGRESQL", 15432, "schema?option", USER, PASSWORD, OWNERSHIP)));
        reject(frame(new Row("POSTGRESQL", 15432, "schema\u00e9", USER, PASSWORD, OWNERSHIP)));
        reject(frame(new Row("POSTGRESQL", 15432, "schema\0", USER, PASSWORD, OWNERSHIP)));
        reject(frame(new Row("POSTGRESQL", 15432, "a".repeat(64), USER, PASSWORD, OWNERSHIP)));
        reject(frame(new Row("POSTGRESQL", 15432, DATABASE, "user@host", PASSWORD, OWNERSHIP)));
        reject(frame(new Row("POSTGRESQL", 15432, DATABASE, USER, "p".repeat(23), OWNERSHIP)));
        reject(frame(new Row("POSTGRESQL", 15432, DATABASE, USER, "p".repeat(129), OWNERSHIP)));
        reject(frame(new Row("POSTGRESQL", 15432, DATABASE, USER, PASSWORD + "=", OWNERSHIP)));
        reject(frame(new Row("POSTGRESQL", 15432, DATABASE, USER, PASSWORD, "f".repeat(31) + "F")));
        reject(frame(new Row("POSTGRESQL", 15432, DATABASE, USER, PASSWORD, "a".repeat(257))));
        reject(Arrays.copyOf(one, one.length - 1));
        reject(Arrays.copyOf(one, one.length + 1));
        var oversized = new ByteArrayInputStream(Arrays.copyOf(one, 8200));
        expectFailure(IllegalArgumentException.class, INVALID_PIPE, () -> DedicatedRuntimeProvider.readPipe(oversized));
        check(oversized.available() == 7);
        InputStream broken = new InputStream() {
            @Override public int read() throws IOException { throw new IOException(PASSWORD); }
        };
        expectFailure(IllegalArgumentException.class, INVALID_PIPE, () -> DedicatedRuntimeProvider.readPipe(broken));
    }

    private static void testDataSources() throws Exception {
        Map<DatabaseProfile, DataSource> sources = DedicatedRuntimeProvider.readPipe(new ByteArrayInputStream(frame(
                row("POSTGRESQL", 1), row("MYSQL", 13306), row("SQLSERVER", 11433), row("ORACLE", 65535))));
        check(sources.size() == 4);
        for (DatabaseProfile profile : DatabaseProfile.values()) {
            check(DriverManager.drivers().noneMatch(driver -> profile.driverClass().equals(driver.getClass().getName())));
        }
        var driver = new FakeDriver();
        PrintWriter originalWriter = DriverManager.getLogWriter();
        DriverManager.registerDriver(driver);
        try {
            DriverManager.setLogWriter(null);
            DataSource postgres = sources.get(DatabaseProfile.POSTGRESQL);
            Map<String, String> postgresOptions = Map.of("connectTimeout", "5", "socketTimeout", "10");
            assertConnection(postgres, driver, "jdbc:postgresql://127.0.0.1:1/" + DATABASE, postgresOptions);
            driver.properties.setProperty("password", "synthetic_changed");
            assertConnection(postgres, driver, "jdbc:postgresql://127.0.0.1:1/" + DATABASE, postgresOptions);
            assertConnection(sources.get(DatabaseProfile.MYSQL), driver, "jdbc:mysql://127.0.0.1:13306/" + DATABASE,
                    Map.of("connectTimeout", "5000", "socketTimeout", "10000", "useSSL", "false",
                            "allowPublicKeyRetrieval", "true"));
            assertConnection(sources.get(DatabaseProfile.SQLSERVER), driver, "jdbc:sqlserver://127.0.0.1:11433",
                    Map.of("databaseName", DATABASE, "loginTimeout", "5", "socketTimeout", "10000",
                            "encrypt", "true", "trustServerCertificate", "true"));
            assertConnection(sources.get(DatabaseProfile.ORACLE), driver,
                    "jdbc:oracle:thin:@//127.0.0.1:65535/" + DATABASE,
                    Map.of("oracle.net.CONNECT_TIMEOUT", "5000", "oracle.jdbc.ReadTimeout", "10000"));

            int calls = driver.calls;
            var capture = new ByteArrayOutputStream();
            try (var writer = new PrintWriter(capture)) {
                check(postgres.getLogWriter() == null && postgres.getLoginTimeout() == 5);
                check(postgres.isWrapperFor(DataSource.class) && postgres.unwrap(DataSource.class) == postgres);
                check(!postgres.isWrapperFor(Properties.class));
                check(!postgres.toString().contains(DATABASE) && !postgres.toString().contains(USER)
                        && !postgres.toString().contains(PASSWORD));
                expectFailure(SQLFeatureNotSupportedException.class, "Dedicated database wrapper is unavailable",
                        () -> postgres.unwrap(Properties.class));
                expectFailure(SQLFeatureNotSupportedException.class, "Dedicated database credentials are fixed",
                        () -> postgres.getConnection(USER, PASSWORD));
                expectFailure(SQLFeatureNotSupportedException.class, "Dedicated database timeout is fixed",
                        () -> postgres.setLoginTimeout(0));
                expectFailure(SQLFeatureNotSupportedException.class, LOGGING_DISABLED,
                        () -> postgres.setLogWriter(writer));
                expectFailure(SQLFeatureNotSupportedException.class, LOGGING_DISABLED, postgres::getParentLogger);
                DriverManager.setLogWriter(writer);
                expectFailure(IllegalStateException.class, LOGGING_DISABLED, postgres::getConnection);
                DriverManager.setLogWriter(null);
                writer.flush();
                check(driver.calls == calls && capture.size() == 0);
            }
            var sensitiveFailure = new SQLException(PASSWORD, "DUMMY", 1, new IOException(DATABASE));
            sensitiveFailure.setNextException(new SQLException(USER));
            driver.failure = sensitiveFailure;
            expectFailure(SQLException.class, "Dedicated database connection failed", postgres::getConnection);
            check(driver.calls == calls + 1);
        } finally {
            DriverManager.deregisterDriver(driver);
            DriverManager.setLogWriter(originalWriter);
        }
    }

    private static void assertConnection(DataSource source, FakeDriver driver, String expectedUrl,
                                         Map<String, String> options) throws SQLException {
        check(source.getConnection() == driver.connection);
        check(expectedUrl.equals(driver.url));
        check(driver.properties.size() == options.size() + 2);
        check(driver.properties.entrySet().containsAll(options.entrySet()));
        check(USER.equals(driver.properties.getProperty("user")));
        check(PASSWORD.equals(driver.properties.getProperty("password")));
    }

    private static void reject(byte[] bytes) throws Exception {
        expectFailure(IllegalArgumentException.class, INVALID_PIPE,
                () -> DedicatedRuntimeProvider.readPipe(new ByteArrayInputStream(bytes)));
    }

    private static Row row(String profile, int port) {
        return new Row(profile, port, DATABASE, USER, PASSWORD, OWNERSHIP);
    }

    private static byte[] frame(Row... rows) throws IOException {
        return frame(MAGIC, 1, rows.length, rows);
    }

    private static byte[] frame(int magic, int version, int count, Row... rows) throws IOException {
        var bytes = new ByteArrayOutputStream();
        try (var output = new DataOutputStream(bytes)) {
            output.writeInt(magic);
            output.writeInt(version);
            output.writeInt(count);
            for (Row row : rows) {
                output.writeUTF(row.profile());
                output.writeInt(row.port());
                output.writeUTF(row.database());
                output.writeUTF(row.user());
                output.writeUTF(row.password());
                output.writeUTF(row.ownership());
            }
        }
        return bytes.toByteArray();
    }

    private static void expectFailure(Class<? extends Exception> type, String message, CheckedOperation operation)
            throws Exception {
        try {
            operation.run();
        } catch (Exception ex) {
            check(ex.getClass() == type && message.equals(ex.getMessage()));
            check(ex.getCause() == null && ex.getSuppressed().length == 0);
            if (ex instanceof SQLException sql) check(sql.getNextException() == null && sql.getSQLState() == null);
            return;
        }
        throw new AssertionError("Expected provider failure");
    }

    private static void check(boolean condition) {
        assertions++;
        if (!condition) throw new AssertionError("Provider assertion failed at check " + assertions);
    }

    @FunctionalInterface
    private interface CheckedOperation { void run() throws Exception; }

    private record Row(String profile, int port, String database, String user, String password, String ownership) { }

    private static final class CountingInput extends InputStream {
        private final ByteArrayInputStream delegate;
        private int calls;

        private CountingInput(byte[] bytes) { delegate = new ByteArrayInputStream(bytes); }

        @Override public int read() { calls++; return delegate.read(); }
        @Override public int read(byte[] bytes, int offset, int length) {
            calls++;
            return delegate.read(bytes, offset, length);
        }
    }

    private static final class FakeDriver implements Driver {
        private final Connection connection = (Connection) Proxy.newProxyInstance(Connection.class.getClassLoader(),
                new Class<?>[] {Connection.class}, (proxy, method, arguments) -> {
                    throw new AssertionError("Unexpected fake JDBC connection operation");
                });
        private String url;
        private Properties properties;
        private SQLException failure;
        private int calls;

        @Override
        public Connection connect(String url, Properties properties) throws SQLException {
            calls++;
            this.url = url;
            this.properties = properties;
            if (failure != null) throw failure;
            return connection;
        }

        @Override public boolean acceptsURL(String url) { return url.startsWith("jdbc:"); }
        @Override public DriverPropertyInfo[] getPropertyInfo(String url, Properties properties) {
            return new DriverPropertyInfo[0];
        }
        @Override public int getMajorVersion() { return 1; }
        @Override public int getMinorVersion() { return 0; }
        @Override public boolean jdbcCompliant() { return false; }
        @Override public Logger getParentLogger() throws SQLFeatureNotSupportedException {
            throw new SQLFeatureNotSupportedException();
        }
    }
}
