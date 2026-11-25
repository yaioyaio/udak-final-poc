package dev.udak.schema;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.lang.reflect.Proxy;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.SQLException;
import java.util.Map;
import java.util.Properties;
import java.util.regex.Pattern;

/** Runs the column contract on a disposable, loopback-only MySQL fixture. */
public final class SchemaSnapshotCollectorMySqlTest {
    private static final String CATALOG = "udak_fixture";
    private static final String LOCAL = "contract_item";
    private static final String DEVELOPMENT = "contract%development";
    private static final String COLUMNS = "(quantity INT NOT NULL, sequence_id BIGINT NOT NULL,"
            + " label VARCHAR(32), note VARCHAR(16) NOT NULL, legacy_col DATE, balance DECIMAL(8,2),"
            + " updated_at TIMESTAMP NULL, description TEXT) DEFAULT CHARACTER SET utf8mb4";
    private static final int QUERY_TIMEOUT_SECONDS = 5;
    private static final Pattern DRIVER_VERSION = Pattern.compile(
            "mysql-connector-j-(26\\.10\\.0) \\(Revision: [A-Za-z0-9._-]{1,128}\\)");

    private final int port;
    private final String password;
    private final String revision;
    private final Path work;
    private int assertions;

    private SchemaSnapshotCollectorMySqlTest(int port, String password, String revision, Path work) {
        this.port = port;
        this.password = password;
        this.revision = revision;
        this.work = work;
    }

    public static void main(String[] args) {
        try (var input = new BufferedReader(new InputStreamReader(System.in, StandardCharsets.UTF_8))) {
            if (args.length != 3) throw new IllegalArgumentException();
            int port = Integer.parseInt(args[0]);
            String password = input.readLine();
            if (port < 1 || port > 65535 || password == null || !password.matches("[a-f0-9]{48}")) {
                throw new IllegalArgumentException();
            }
            new SchemaSnapshotCollectorMySqlTest(port, password, args[1], Path.of(args[2])).verify();
        } catch (Exception | LinkageError failure) {
            System.err.println("MySQL schema collector contract failed");
            System.exit(1);
        }
    }

    private Connection connect() throws SQLException {
        var properties = new Properties();
        properties.setProperty("user", "udak_fixture");
        properties.setProperty("password", password);
        properties.setProperty("databaseTerm", "CATALOG");
        properties.setProperty("useInformationSchema", "true");
        properties.setProperty("connectTimeout", "4000");
        properties.setProperty("socketTimeout", "5000");
        properties.setProperty("sslMode", "DISABLED");
        return DriverManager.getConnection("jdbc:mysql://127.0.0.1:" + port + "/" + CATALOG, properties);
    }

    private void verify() throws Exception {
        String server;
        String driver;
        try (var owner = connect(); var ddl = owner.createStatement()) {
            var metadata = owner.getMetaData();
            server = metadata.getDatabaseProductVersion();
            check("MySQL".equals(metadata.getDatabaseProductName()) && server.matches("8\\.0\\.[0-9]{1,3}"));
            var release = DRIVER_VERSION.matcher(metadata.getDriverVersion());
            check(release.matches());
            driver = release.group(1);
            ddl.setQueryTimeout(QUERY_TIMEOUT_SECONDS);
            ddl.executeUpdate("CREATE TABLE `" + LOCAL + "` " + COLUMNS);
            ddl.executeUpdate("CREATE TABLE `" + DEVELOPMENT + "` " + COLUMNS);
            ddl.executeUpdate("CREATE TABLE contractxitem (decoy_col INT)");
            ddl.executeUpdate("CREATE TABLE contractxdevelopment (decoy_col INT)");
            ddl.executeUpdate("CREATE VIEW contract_view AS SELECT quantity FROM contract_item");
            ddl.executeUpdate("CREATE TABLE json_item (payload JSON)");
            ddl.executeUpdate("CREATE TABLE unsigned_item (quantity INT UNSIGNED)");
            ddl.executeUpdate("CREATE TABLE datetime_item (updated_at DATETIME)");
        }
        String baseline = snapshot("baseline", LOCAL, true);
        check(baseline.equals(snapshot("equal", DEVELOPMENT, false)));
        try (var owner = connect(); var ddl = owner.createStatement()) {
            ddl.setQueryTimeout(QUERY_TIMEOUT_SECONDS);
            ddl.executeUpdate("ALTER TABLE `" + DEVELOPMENT + "` DROP COLUMN legacy_col,"
                    + " ADD COLUMN added_col DATE, MODIFY quantity BIGINT NOT NULL,"
                    + " MODIFY label VARCHAR(64), MODIFY note VARCHAR(16) NULL");
        }
        check(!baseline.equals(snapshot("drift", DEVELOPMENT, false)));
        System.out.println("assertions=" + assertions);
        System.out.println("server_version=" + server);
        System.out.println("driver_version=" + driver);
    }

    private String snapshot(String name, String table, boolean verifyRejections) throws Exception {
        try (var reader = connect()) {
            reader.setReadOnly(true);
            reader.setAutoCommit(false);
            assertReadOnly(reader);
            var metadata = reader.getMetaData();
            var metadataOnly = Connection.class.cast(Proxy.newProxyInstance(Connection.class.getClassLoader(),
                    new Class<?>[]{Connection.class}, (ignored, method, args) -> {
                        if ("getMetaData".equals(method.getName())) return metadata;
                        throw new IllegalStateException("Unexpected connection operation");
                    }));
            String result = collect(metadataOnly, CATALOG, null, table);
            check(!result.contains(CATALOG) && !result.contains(table) && !result.contains("decoy_col"));
            if (verifyRejections) {
                expectRejected(metadataOnly, null, null, table);
                expectRejected(metadataOnly, "missing_catalog", null, table);
                expectRejected(metadataOnly, CATALOG, "fixture_schema", table);
                expectRejected(metadataOnly, CATALOG, null, "missing_table");
                expectRejected(metadataOnly, CATALOG, null, "contract_view");
                expectRejected(metadataOnly, CATALOG, null, "json_item");
                expectRejected(metadataOnly, CATALOG, null, "unsigned_item");
                expectRejected(metadataOnly, CATALOG, null, "datetime_item");
            }
            assertReadOnly(reader);
            reader.rollback();
            Files.writeString(work.resolve(name).resolve("SCHEMA-SNAPSHOT.json"), result,
                    StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE);
            return result;
        }
    }

    private String collect(Connection reader, String catalog, String schema, String table) throws SQLException {
        return SchemaSnapshotCollector.collect(reader, revision, catalog, schema, Map.of("stock_item", table));
    }

    private void expectRejected(Connection reader, String catalog, String schema, String table) throws SQLException {
        try {
            collect(reader, catalog, schema, table);
        } catch (SQLException failure) {
            check("Schema snapshot collection failed".equals(failure.getMessage())
                    && failure.getCause() == null && failure.getNextException() == null);
            return;
        }
        throw new SQLException("Unexpected acceptance of invalid MySQL metadata");
    }

    private void assertReadOnly(Connection reader) throws SQLException {
        check(reader.isReadOnly() && !reader.getAutoCommit() && CATALOG.equals(reader.getCatalog()));
        try (var statement = reader.createStatement()) {
            statement.setQueryTimeout(QUERY_TIMEOUT_SECONDS);
            try (var rows = statement.executeQuery("SELECT @@session.transaction_read_only")) {
                check(rows.next() && rows.getInt(1) == 1 && !rows.next());
            }
        }
    }

    private void check(boolean condition) throws SQLException {
        if (!condition) throw new SQLException("MySQL schema collector assertion failed");
        assertions++;
    }
}
