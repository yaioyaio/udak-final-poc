package dev.udak.schema;

import dev.udak.schema.FlywayHistoryCollector.AppliedArtifact;
import dev.udak.schema.FlywayHistoryCollector.Status;
import dev.udak.inventory.InventoryCapture;
import dev.udak.observe.SqlObserver;
import dev.udak.observe.jdbc.ObserveDataSource;
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
import java.util.Map;
import java.util.Objects;
import java.util.Properties;
import java.util.UUID;
import org.flywaydb.core.Flyway;
import org.postgresql.ds.PGSimpleDataSource;

/** Applies the reviewed fixture with Flyway and collects its actual history using JDBC. */
public final class FlywayHistoryPostgreSqlTest {
    private static final String CATALOG = "postgres";
    private static final String TARGET = "flyway_case";
    private static final String NO_HISTORY = "missing_case";
    private final String url;
    private final String password;
    private int assertions;

    private record PrQuery(String sql, UUID tenant, String queryId, String testId) {}

    private FlywayHistoryPostgreSqlTest(String port, String password) {
        this.url = "jdbc:postgresql://127.0.0.1:" + port + "/" + CATALOG;
        this.password = password;
    }

    public static void main(String[] args) throws Exception {
        try (var input = new BufferedReader(new InputStreamReader(System.in, StandardCharsets.UTF_8))) {
            var test = new FlywayHistoryPostgreSqlTest(args[0], input.readLine());
            String sql = input.readLine();
            PrQuery query = sql == null ? null : new PrQuery(
                    sql, UUID.fromString(input.readLine()), input.readLine(), input.readLine());
            test.verify(Path.of(args[1]), args[2], args[3], args[4], args[5], query);
            System.out.println("assertions=" + test.assertions);
        }
    }

    private void verify(Path work, String base, String head, String scope, String approvedHash,
            PrQuery query) throws Exception {
        try (var connection = connect(); var ddl = connection.createStatement()) {
            check(connection.getMetaData().getDatabaseMajorVersion() == 18);
            check("42.7.14".equals(connection.getMetaData().getDriverVersion()));
            ddl.execute("CREATE SCHEMA flyway_case");
            ddl.execute("CREATE SCHEMA missing_case");
        }
        var empty = flyway(work.resolve("empty")).migrate();
        check(empty.success && empty.migrationsExecuted == 0);
        seed(TARGET, query != null);
        seed(NO_HISTORY, query != null);
        if (query != null) {
            observePrQuery(work.resolve("baseline/SQL-INVENTORY.json"), base, scope, query);
        }
        capture(work.resolve("baseline"), TARGET, base, scope, null, null, Status.EMPTY);

        Path script = work.resolve("reviewed/V002__DROP_DEVICE_CUSTOMER_ID.sql");
        check(approvedHash.equals(sha256(script)));
        var flyway = flyway(script.getParent());
        var pending = flyway.info().pending();
        check(pending.length == 1 && Integer.parseInt(pending[0].getVersion().getVersion()) == 2
                && script.getFileName().toString().equals(pending[0].getScript())
                && pending[0].getResolvedChecksum() != null);
        String version = pending[0].getVersion().getVersion();
        Integer crc = pending[0].getResolvedChecksum();
        var result = flyway.migrate();
        check(result.success && result.migrationsExecuted == 1);
        check(approvedHash.equals(sha256(script)) && flyway.validateWithResult().validationSuccessful);
        var applied = flyway.info().applied();
        check(applied.length == 1 && version.equals(applied[0].getVersion().getVersion())
                && script.getFileName().toString().equals(applied[0].getScript())
                && Objects.equals(crc, applied[0].getAppliedChecksum())
                && Objects.equals(crc, applied[0].getResolvedChecksum())
                && applied[0].getInstalledRank() != null);
        var artifact = new AppliedArtifact(CATALOG, TARGET, applied[0].getInstalledRank(),
                version, script.getFileName().toString(), crc, approvedHash);
        capture(work.resolve("matched"), TARGET, head, scope, artifact, script, Status.VERIFIED);

        try (var connection = connect(); var ddl = connection.createStatement()) {
            connection.setSchema(NO_HISTORY);
            check(NO_HISTORY.equals(connection.getSchema()));
            ddl.execute(Files.readString(script, StandardCharsets.UTF_8));
        }
        capture(work.resolve("missing"), NO_HISTORY, head, scope, null, null, Status.EMPTY);
        capture(work.resolve("missing-proof"), TARGET, head, scope, null, script, Status.HISTORY_FILE_UNVERIFIED);

        Path alternate = work.resolve("alternate").resolve(script.getFileName());
        check(!approvedHash.equals(sha256(alternate)));
        var alternateFlyway = flyway(alternate.getParent());
        var alternateApplied = alternateFlyway.info().applied();
        check(alternateApplied.length == 1 && Objects.equals(crc, alternateApplied[0].getResolvedChecksum())
                && alternateFlyway.validateWithResult().validationSuccessful);
        capture(work.resolve("same-crc-different-file"), TARGET, head, scope, artifact, alternate,
                Status.HISTORY_FILE_UNVERIFIED);
        System.out.println("native_checksum=" + crc);
    }

    private Flyway flyway(Path location) {
        return Flyway.configure().dataSource(url, "postgres", password).schemas(TARGET).defaultSchema(TARGET)
                .locations("filesystem:" + location).createSchemas(false).placeholderReplacement(false)
                .cleanDisabled(true).validateMigrationNaming(true).loggers().load();
    }

    private Connection connect() throws SQLException {
        var properties = new Properties();
        properties.setProperty("user", "postgres");
        properties.setProperty("password", password);
        properties.setProperty("connectTimeout", "4");
        properties.setProperty("socketTimeout", "5");
        return DriverManager.getConnection(url, properties);
    }

    private void seed(String schema, boolean prReport) throws SQLException {
        try (var connection = connect(); var ddl = connection.createStatement()) {
            connection.setSchema(schema);
            check(schema.equals(connection.getSchema()));
            ddl.execute("CREATE TABLE device (id uuid PRIMARY KEY, customer_id uuid, fixture_note varchar(16))");
            if (prReport) {
                ddl.execute("ALTER TABLE device ADD COLUMN tenant_id uuid NOT NULL,"
                        + " ADD COLUMN device_profile_id uuid NOT NULL, ADD COLUMN created_time bigint NOT NULL");
            }
        }
    }

    private void observePrQuery(Path output, String revision, String scope, PrQuery query) throws Exception {
        UUID device = UUID.randomUUID();
        UUID customer = UUID.randomUUID();
        try (var owner = connect(); var insert = owner.prepareStatement(
                "INSERT INTO flyway_case.device (id, customer_id, tenant_id, device_profile_id, created_time)"
                        + " VALUES (?, ?, ?, ?, 1)")) {
            insert.setObject(1, device);
            insert.setObject(2, customer);
            insert.setObject(3, query.tenant());
            insert.setObject(4, UUID.randomUUID());
            check(insert.executeUpdate() == 1);
        }
        var source = new PGSimpleDataSource();
        source.setURL(url);
        source.setUser("postgres");
        source.setPassword(password);
        source.setCurrentSchema(TARGET);
        source.setConnectTimeout(4);
        source.setSocketTimeout(5);
        var inventory = new InventoryCapture();
        var observed = new ObserveDataSource(source, new SqlObserver(inventory));
        try (var reader = observed.getConnection()) {
            reader.setReadOnly(true);
            reader.setAutoCommit(false);
            try (var registered = inventory.scope(query.queryId(), query.testId());
                    var statement = reader.createStatement(); var rows = statement.executeQuery(query.sql())) {
                check(rows.next() && device.equals(rows.getObject("id", UUID.class))
                        && customer.equals(rows.getObject("customerid", UUID.class)) && !rows.next());
            }
            reader.rollback();
        }
        Files.writeString(output, inventory.snapshotJsonWithObservedTests(revision, scope));
    }

    private void capture(Path directory, String schema, String revision, String scope, AppliedArtifact proof,
            Path file, Status expected) throws Exception {
        try (var reader = connect()) {
            reader.setReadOnly(true);
            reader.setAutoCommit(false);
            try (var statement = reader.createStatement();
                    var result = statement.executeQuery("SHOW transaction_read_only")) {
                check(result.next() && "on".equals(result.getString(1)) && !result.next());
            }
            String snapshot = SchemaSnapshotCollector.collect(reader, revision, CATALOG, schema, Map.of("device", "device"));
            var export = FlywayHistoryCollector.collect(reader, revision, scope, schema, proof, file);
            check(export.status() == expected && reader.isReadOnly() && !reader.getAutoCommit());
            Files.writeString(directory.resolve("SCHEMA-SNAPSHOT.json"), snapshot);
            if (export.historyJson() != null) {
                Files.writeString(directory.resolve("MIGRATION-HISTORY.json"), export.historyJson());
            }
            Files.writeString(directory.resolve("status"), export.status().name());
            reader.rollback();
        }
    }

    private static String sha256(Path file) throws Exception {
        return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(Files.readAllBytes(file)));
    }

    private void check(boolean condition) throws SQLException {
        if (!condition) {
            throw new SQLException("Flyway fixture assertion failed");
        }
        assertions++;
    }
}
