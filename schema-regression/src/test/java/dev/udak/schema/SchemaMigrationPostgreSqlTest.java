package dev.udak.schema;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.SQLException;
import java.util.HexFormat;
import java.util.List;
import java.util.Map;
import java.util.Properties;
import java.util.StringJoiner;

/** Captures PostgreSQL schema metadata and ordered history from disposable fixtures. */
public final class SchemaMigrationPostgreSqlTest {
    private static final String CATALOG = "postgres";
    private static final String CREATE_DEVICE =
            "CREATE TABLE device (id uuid PRIMARY KEY, customer_id uuid, fixture_note varchar(16))";
    private static final List<String> FIXTURES = List.of("baseline", "matched", "missing", "wrong_version",
            "wrong_checksum", "extra_change");

    private final String url;
    private final Properties properties = new Properties();
    private int assertions;

    private SchemaMigrationPostgreSqlTest(String port, String password) {
        url = "jdbc:postgresql://127.0.0.1:" + port + "/" + CATALOG;
        properties.setProperty("user", "postgres");
        properties.setProperty("password", password);
        properties.setProperty("connectTimeout", "4");
        properties.setProperty("socketTimeout", "5");
    }

    public static void main(String[] args) throws Exception {
        try (var input = new BufferedReader(new InputStreamReader(System.in, StandardCharsets.UTF_8))) {
            var test = new SchemaMigrationPostgreSqlTest(args[0], input.readLine());
            Path work = Path.of(args[1]);
            String sql = Files.readString(Path.of(args[2]), StandardCharsets.UTF_8);
            test.verify(work, sql, args[3], args[4], args[5], args[6]);
            System.out.println("assertions=" + test.assertions);
        }
    }

    private void verify(Path work, String sql, String baseRevision, String headRevision,
            String scope, String checksum) throws Exception {
        check(digest(sql).equals(checksum));
        try (var connection = connect()) {
            check(connection.getMetaData().getDatabaseMajorVersion() == 18);
            check(connection.getMetaData().getDriverVersion().equals("42.7.14"));
        }
        for (String fixture : FIXTURES) {
            prepare(fixture, sql);
            capture(work.resolve(fixture), fixture, fixture.equals("baseline") ? baseRevision : headRevision, scope);
        }
    }

    private Connection connect() throws SQLException {
        return DriverManager.getConnection(url, properties);
    }

    private void prepare(String schema, String reviewedSql) throws Exception {
        try (var owner = connect(); var ddl = owner.createStatement()) {
            owner.setAutoCommit(false);
            ddl.execute("CREATE SCHEMA " + schema);
            owner.setSchema(schema);
            check(schema.equals(owner.getSchema()));
            ddl.execute(CREATE_DEVICE);
            ddl.execute("CREATE TABLE fixture_migration_history (applied_order bigint GENERATED ALWAYS AS IDENTITY"
                    + " PRIMARY KEY, version varchar(32) NOT NULL UNIQUE, checksum_sha256 varchar(64) NOT NULL)");
            record(owner, "1", digest(CREATE_DEVICE));
            if (!schema.equals("baseline")) {
                String sql = schema.equals("wrong_checksum") ? reviewedSql + "-- alternate fixture bytes\n" : reviewedSql;
                ddl.execute(sql);
                if (!schema.equals("missing")) {
                    record(owner, schema.equals("wrong_version") ? "3" : "2", digest(sql));
                }
                if (schema.equals("extra_change")) {
                    ddl.execute("ALTER TABLE device ALTER COLUMN fixture_note TYPE varchar(32)");
                }
            }
            owner.commit();
        }
    }

    private void capture(Path directory, String schema, String revision, String scope) throws Exception {
        try (var reader = connect()) {
            reader.setSchema(schema);
            reader.setReadOnly(true);
            reader.setAutoCommit(false);
            try (var statement = reader.createStatement();
                    var row = statement.executeQuery("SHOW transaction_read_only")) {
                check(row.next() && "on".equals(row.getString(1)) && !row.next());
            }
            check(CATALOG.equals(reader.getCatalog()) && schema.equals(reader.getSchema()));
            Files.writeString(directory.resolve("SCHEMA-SNAPSHOT.json"),
                    SchemaSnapshotCollector.collect(reader, revision, CATALOG, schema, Map.of("device", "device")));

            var history = new StringJoiner(",");
            int count = 0;
            try (var statement = reader.createStatement(); var rows = statement.executeQuery(
                    "SELECT version, checksum_sha256 FROM fixture_migration_history ORDER BY applied_order")) {
                while (rows.next()) {
                    String version = rows.getString("version");
                    String hash = rows.getString("checksum_sha256");
                    check(++count <= 2 && version.matches("[1-9][0-9]{0,8}") && hash.matches("[a-f0-9]{64}"));
                    history.add("{\"version\":\"" + version + "\",\"checksum_sha256\":\"" + hash + "\"}");
                }
            }
            Files.writeString(directory.resolve("MIGRATION-HISTORY.json"), "{\"schema_version\":1,\"revision\":\""
                    + revision + "\",\"scope\":\"" + scope + "\",\"migrations\":[" + history + "]}\n");
            reader.rollback();
        }
    }

    private void record(Connection owner, String version, String checksum) throws SQLException {
        try (var insert = owner.prepareStatement(
                "INSERT INTO fixture_migration_history (version, checksum_sha256) VALUES (?, ?)")) {
            insert.setString(1, version);
            insert.setString(2, checksum);
            check(insert.executeUpdate() == 1);
        }
    }

    private static String digest(String value) throws Exception {
        return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256")
                .digest(value.getBytes(StandardCharsets.UTF_8)));
    }

    private void check(boolean condition) throws SQLException {
        if (!condition) {
            throw new SQLException("PostgreSQL migration fixture assertion failed");
        }
        assertions++;
    }
}
