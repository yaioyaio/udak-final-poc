package dev.udak.schema;

import dev.udak.schema.FlywayHistoryCollector.AppliedArtifact;
import dev.udak.schema.FlywayHistoryCollector.Status;
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
import org.flywaydb.core.Flyway;

/** Applies the reviewed fixture with Flyway and collects its actual history using JDBC. */
public final class FlywayHistoryPostgreSqlTest {
    private static final String CATALOG = "postgres";
    private static final String TARGET = "flyway_case";
    private static final String NO_HISTORY = "missing_case";
    private final String url;
    private final String password;
    private int assertions;

    private FlywayHistoryPostgreSqlTest(String port, String password) {
        this.url = "jdbc:postgresql://127.0.0.1:" + port + "/" + CATALOG;
        this.password = password;
    }

    public static void main(String[] args) throws Exception {
        try (var input = new BufferedReader(new InputStreamReader(System.in, StandardCharsets.UTF_8))) {
            var test = new FlywayHistoryPostgreSqlTest(args[0], input.readLine());
            test.verify(Path.of(args[1]), args[2], args[3], args[4], args[5]);
            System.out.println("assertions=" + test.assertions);
        }
    }

    private void verify(Path work, String base, String head, String scope, String approvedHash) throws Exception {
        try (var connection = connect(); var ddl = connection.createStatement()) {
            check(connection.getMetaData().getDatabaseMajorVersion() == 18);
            check("42.7.14".equals(connection.getMetaData().getDriverVersion()));
            ddl.execute("CREATE SCHEMA flyway_case");
            ddl.execute("CREATE SCHEMA missing_case");
        }
        var empty = flyway(work.resolve("empty")).migrate();
        check(empty.success && empty.migrationsExecuted == 0);
        seed(TARGET);
        seed(NO_HISTORY);
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

    private void seed(String schema) throws SQLException {
        try (var connection = connect(); var ddl = connection.createStatement()) {
            connection.setSchema(schema);
            check(schema.equals(connection.getSchema()));
            ddl.execute("CREATE TABLE device (id uuid PRIMARY KEY, customer_id uuid, fixture_note varchar(16))");
        }
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
