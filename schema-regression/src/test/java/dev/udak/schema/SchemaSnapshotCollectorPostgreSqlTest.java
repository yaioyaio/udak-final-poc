package dev.udak.schema;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.SQLException;
import java.util.Map;
import java.util.Properties;

/** Real PostgreSQL contract checks for isolated local and development databases. */
public final class SchemaSnapshotCollectorPostgreSqlTest {
    private static final String LOCAL = "contract_local";
    private static final String DEVELOPMENT = "contract_development";
    private static final String SCHEMA = "device_app";
    private static final String LOCAL_TABLE = "device_catalog";
    private static final String DEVELOPMENT_TABLE = "device_store";
    private static final String COLUMNS = "(id uuid PRIMARY KEY, customer_id uuid, active boolean NOT NULL,"
            + " label varchar(24) NOT NULL, description text, balance numeric(8,2), installed_on date,"
            + " created_at timestamp, sequence_id bigserial, retries integer NOT NULL)";

    private final String port;
    private final String password;
    private final String revision;
    private final Path work;
    private int assertions;

    private SchemaSnapshotCollectorPostgreSqlTest(String port, String password, String revision, Path work) {
        this.port = port;
        this.password = password;
        this.revision = revision;
        this.work = work;
    }

    public static void main(String[] args) throws Exception {
        try (var input = new BufferedReader(new InputStreamReader(System.in, StandardCharsets.UTF_8))) {
            var test = new SchemaSnapshotCollectorPostgreSqlTest(args[0], input.readLine(), args[1], Path.of(args[2]));
            test.verify();
            System.out.println("assertions=" + test.assertions);
        }
    }

    private Connection connect(String database) throws SQLException {
        var properties = new Properties();
        properties.setProperty("user", "postgres");
        properties.setProperty("password", password);
        properties.setProperty("connectTimeout", "4");
        properties.setProperty("socketTimeout", "5");
        return DriverManager.getConnection("jdbc:postgresql://127.0.0.1:" + port + "/" + database, properties);
    }

    private void verify() throws Exception {
        try (var admin = connect("postgres"); var ddl = admin.createStatement()) {
            check(admin.getMetaData().getDatabaseMajorVersion() == 18);
            check(admin.getMetaData().getDriverVersion().equals("42.7.14"));
            ddl.execute("CREATE DATABASE " + LOCAL);
            ddl.execute("CREATE DATABASE " + DEVELOPMENT);
        }
        seed(LOCAL, LOCAL_TABLE);
        seed(DEVELOPMENT, DEVELOPMENT_TABLE);
        check(writeSnapshot("baseline", LOCAL, LOCAL_TABLE, true)
                .equals(writeSnapshot("equal", DEVELOPMENT, DEVELOPMENT_TABLE, false)));

        try (var owner = connect(DEVELOPMENT); var ddl = owner.createStatement()) {
            ddl.execute("ALTER TABLE " + SCHEMA + "." + DEVELOPMENT_TABLE + " DROP COLUMN customer_id");
        }
        writeSnapshot("drift", DEVELOPMENT, DEVELOPMENT_TABLE, false);
    }

    private void seed(String database, String table) throws SQLException {
        try (var owner = connect(database); var ddl = owner.createStatement()) {
            ddl.execute("CREATE SCHEMA " + SCHEMA);
            ddl.execute("CREATE TABLE " + SCHEMA + "." + table + " " + COLUMNS);
            if (database.equals(LOCAL)) {
                // These would match an unescaped schema or table wildcard.
                ddl.execute("CREATE SCHEMA devicexapp");
                ddl.execute("CREATE TABLE devicexapp.device_catalog (unselected integer)");
                ddl.execute("CREATE TABLE device_app.devicexcatalog (unselected integer)");
                ddl.execute("CREATE VIEW device_app.device_view AS SELECT id FROM device_app.device_catalog");
                ddl.execute("CREATE TABLE device_app.timezone_item (created_at timestamptz)");
                ddl.execute("CREATE TABLE device_app.unbounded_item (label varchar)");
            }
        }
    }

    private String writeSnapshot(String name, String database, String table, boolean verifyRejections) throws Exception {
        try (var reader = connect(database)) {
            reader.setReadOnly(true);
            reader.setAutoCommit(false);
            String originalSchema = reader.getSchema();
            assertReadOnly(reader);
            check(database.equals(reader.getCatalog()));
            String snapshot = collect(reader, database, SCHEMA, table);
            if (verifyRejections) {
                expectRejected(reader, DEVELOPMENT, SCHEMA, table);
                expectRejected(reader, database, "missing_schema", table);
                expectRejected(reader, database, SCHEMA, "missing_table");
                expectRejected(reader, database, SCHEMA, "device_view");
                expectRejected(reader, database, SCHEMA, "timezone_item");
                expectRejected(reader, database, SCHEMA, "unbounded_item");
            }
            assertReadOnly(reader);
            check(originalSchema.equals(reader.getSchema()) && database.equals(reader.getCatalog()));
            Files.writeString(work.resolve(name).resolve("SCHEMA-SNAPSHOT.json"), snapshot);
            reader.rollback();
            return snapshot;
        }
    }

    private String collect(Connection reader, String catalog, String schema, String table) throws SQLException {
        return SchemaSnapshotCollector.collect(reader, revision, catalog, schema, Map.of("device", table));
    }

    private void expectRejected(Connection reader, String catalog, String schema, String table) throws SQLException {
        try {
            collect(reader, catalog, schema, table);
        } catch (SQLException failure) {
            check("Schema snapshot collection failed".equals(failure.getMessage()) && failure.getCause() == null);
            return;
        }
        throw new SQLException("Unexpected acceptance of invalid PostgreSQL metadata");
    }

    private void assertReadOnly(Connection reader) throws SQLException {
        check(reader.isReadOnly() && !reader.getAutoCommit());
        try (var statement = reader.createStatement(); var rows = statement.executeQuery("SHOW transaction_read_only")) {
            check(rows.next() && "on".equals(rows.getString(1)) && !rows.next());
        }
    }

    private void check(boolean condition) throws SQLException {
        if (!condition) {
            throw new SQLException("PostgreSQL schema collector assertion failed");
        }
        assertions++;
    }
}
