package dev.udak.schema;

import com.mysql.cj.jdbc.MysqlDataSource;
import dev.udak.inventory.InventoryCapture;
import dev.udak.observe.SqlObserver;
import dev.udak.observe.jdbc.ObserveDataSource;
import dev.udak.schema.FlywayHistoryCollector.AppliedArtifact;
import dev.udak.schema.FlywayHistoryCollector.Status;
import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.security.MessageDigest;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.SQLException;
import java.util.HexFormat;
import java.util.Map;
import java.util.Objects;
import java.util.Properties;
import org.flywaydb.core.Flyway;

/** Exercises actual Flyway SQL history on an isolated, loopback-only MySQL catalog. */
public final class FlywayHistoryMySqlTest {
    private static final String CATALOG = "udak_fixture";
    private static final String SCRIPT = "V002__DROP_DEVICE_CUSTOMER_ID.sql";
    private static final int QUERY_TIMEOUT_SECONDS = 5;

    private final String url;
    private final String password;
    private int assertions;

    private FlywayHistoryMySqlTest(int port, String password) {
        url = "jdbc:mysql://127.0.0.1:" + port + "/" + CATALOG
                + "?databaseTerm=CATALOG&useInformationSchema=true&connectTimeout=4000"
                + "&socketTimeout=5000&sslMode=DISABLED";
        this.password = password;
    }

    public static void main(String[] args) {
        try (var input = new BufferedReader(new InputStreamReader(System.in, StandardCharsets.UTF_8))) {
            if (args.length != 7) throw new IllegalArgumentException();
            int port = Integer.parseInt(args[0]);
            String password = input.readLine();
            if (port < 1 || port > 65535 || password == null || !password.matches("[a-f0-9]{48}")) {
                throw new IllegalArgumentException();
            }
            var fixture = new FlywayHistoryMySqlTest(port, password);
            fixture.verify(Path.of(args[1]), args[2], args[3], args[4], args[5], args[6]);
            System.out.println("assertions=" + fixture.assertions);
            System.out.println("server_version=8.0.46");
        } catch (Exception | LinkageError failure) {
            int line = 0;
            for (var frame : failure.getStackTrace()) {
                if (frame.getClassName().equals(FlywayHistoryMySqlTest.class.getName())) {
                    line = Math.max(0, frame.getLineNumber());
                    break;
                }
            }
            System.out.println("fixture_failure_line=" + line);
            System.exit(1);
        }
    }

    private void verify(Path work, String base, String head, String scope, String approvedHash, String alternateHash)
            throws Exception {
        try (var owner = connect()) {
            var metadata = owner.getMetaData();
            check("MySQL".equals(metadata.getDatabaseProductName())
                    && "8.0.46".equals(metadata.getDatabaseProductVersion()));
            check(metadata.getDriverVersion().matches(
                    "mysql-connector-j-26\\.10\\.0 \\(Revision: [A-Za-z0-9._-]{1,128}\\)"));
        }
        check(!approvedHash.equals(alternateHash));
        initializeHistory(work.resolve("empty"));
        execute("CREATE TABLE device (id INT PRIMARY KEY, customer_id INT)");
        String baseline = capture(work.resolve("baseline"), base, scope, null, null, Status.EMPTY);
        observeBaseline(work.resolve("baseline/SQL-INVENTORY.json"), base, scope);

        Path reviewed = work.resolve("reviewed").resolve(SCRIPT);
        AppliedArtifact approved = apply(reviewed, approvedHash);
        String matched = capture(work.resolve("matched"), head, scope, approved, reviewed, Status.VERIFIED);
        check(baseline.contains("\"column\":\"customer_id\"") && !matched.contains("\"column\":\"customer_id\""));
        check(matched.equals(capture(work.resolve("unverified"), head, scope, null, reviewed,
                Status.HISTORY_FILE_UNVERIFIED)));

        execute("RENAME TABLE flyway_schema_history TO history_saved");
        try {
            check(matched.equals(capture(work.resolve("missing"), head, scope, null, null, Status.EMPTY)));
        } finally {
            execute("RENAME TABLE history_saved TO flyway_schema_history");
        }

        execute("DROP TABLE device");
        execute("DROP TABLE flyway_schema_history");
        initializeHistory(work.resolve("empty"));
        execute("CREATE TABLE device (id INT PRIMARY KEY, customer_id INT)");
        Path alternate = work.resolve("alternate").resolve(SCRIPT);
        AppliedArtifact different = apply(alternate, alternateHash);
        check(approved.rank() == different.rank() && approved.version().equals(different.version())
                && approved.script().equals(different.script()) && approved.flywayChecksum() != different.flywayChecksum());
        check(matched.equals(capture(work.resolve("wrong-checksum"), head, scope, different, alternate, Status.VERIFIED)));
        try (var reader = connect()) {
            configureReader(reader);
            var cannotUseOldProof = FlywayHistoryCollector.collectMySql(reader, head, scope, CATALOG, approved, reviewed);
            check(cannotUseOldProof.status() == Status.HISTORY_FILE_UNVERIFIED && cannotUseOldProof.historyJson() == null);
            assertReadOnly(reader);
            reader.rollback();
        }
    }

    private void initializeHistory(Path empty) throws SQLException {
        var result = flyway(empty).migrate();
        check(result.success && result.migrationsExecuted == 0);
        try (var owner = connect(); var statement = owner.createStatement()) {
            statement.setQueryTimeout(QUERY_TIMEOUT_SECONDS);
            try (var rows = statement.executeQuery("SELECT installed_rank FROM flyway_schema_history LIMIT 1")) {
                check(!rows.next());
            }
        }
    }

    private void observeBaseline(Path output, String revision, String scope) throws Exception {
        try (var owner = connect(); var insert = owner.prepareStatement("INSERT INTO device (id, customer_id) VALUES (?, ?)")) {
            insert.setQueryTimeout(QUERY_TIMEOUT_SECONDS);
            insert.setInt(1, 1);
            insert.setInt(2, 2);
            check(insert.executeUpdate() == 1);
        }
        var source = new MysqlDataSource();
        source.setURL(url);
        source.setUser(CATALOG);
        source.setPassword(password);
        var inventory = new InventoryCapture();
        var observed = new ObserveDataSource(source, new SqlObserver(inventory));
        try (var reader = observed.getConnection(); var statement = reader.createStatement()) {
            reader.setReadOnly(true);
            reader.setAutoCommit(false);
            statement.setQueryTimeout(QUERY_TIMEOUT_SECONDS);
            try (var registered = inventory.scope("mysql-flyway-device-query", "mysql-flyway-device-contract");
                    var rows = statement.executeQuery("SELECT id, customer_id FROM device")) {
                check(rows.next() && rows.getInt("id") == 1 && rows.getInt("customer_id") == 2 && !rows.next());
            }
            reader.rollback();
        }
        write(output, inventory.snapshotJsonWithObservedTests(revision, scope));
    }

    private AppliedArtifact apply(Path script, String sha256) throws Exception {
        check(sha256.equals(digest(script)));
        var flyway = flyway(script.getParent());
        var pending = flyway.info().pending();
        check(pending.length == 1 && pending[0].getVersion() != null
                && Integer.parseInt(pending[0].getVersion().getVersion()) == 2
                && SCRIPT.equals(pending[0].getScript()) && pending[0].getResolvedChecksum() != null);
        String version = pending[0].getVersion().getVersion();
        Integer checksum = pending[0].getResolvedChecksum();
        var result = flyway.migrate();
        check(result.success && result.migrationsExecuted == 1);
        check(sha256.equals(digest(script)) && flyway.validateWithResult().validationSuccessful);
        var applied = flyway.info().applied();
        check(applied.length == 1 && applied[0].getVersion() != null
                && version.equals(applied[0].getVersion().getVersion()) && SCRIPT.equals(applied[0].getScript())
                && Objects.equals(checksum, applied[0].getAppliedChecksum())
                && Objects.equals(checksum, applied[0].getResolvedChecksum())
                && applied[0].getInstalledRank() != null && applied[0].getInstalledRank() > 0);
        return new AppliedArtifact(CATALOG, null, applied[0].getInstalledRank(), version, SCRIPT, checksum, sha256);
    }

    private Flyway flyway(Path location) {
        return Flyway.configure().dataSource(url, CATALOG, password).schemas(CATALOG).defaultSchema(CATALOG)
                .locations("filesystem:" + location).createSchemas(false).placeholderReplacement(false)
                .cleanDisabled(true).validateMigrationNaming(true).loggers().load();
    }

    private Connection connect() throws SQLException {
        var properties = new Properties();
        properties.setProperty("user", CATALOG);
        properties.setProperty("password", password);
        return DriverManager.getConnection(url, properties);
    }

    private void execute(String sql) throws SQLException {
        try (var owner = connect(); var statement = owner.createStatement()) {
            statement.setQueryTimeout(QUERY_TIMEOUT_SECONDS);
            statement.executeUpdate(sql);
        }
    }

    private String capture(Path directory, String revision, String scope, AppliedArtifact proof, Path file,
            Status expected) throws Exception {
        try (var reader = connect()) {
            configureReader(reader);
            String snapshot = SchemaSnapshotCollector.collect(reader, revision, CATALOG, null, Map.of("device", "device"));
            var export = FlywayHistoryCollector.collectMySql(reader, revision, scope, CATALOG, proof, file);
            check(export.status() == expected);
            check((export.historyJson() == null) == (expected == Status.HISTORY_FILE_UNVERIFIED));
            if (expected == Status.VERIFIED) {
                rejectMismatchedCatalog(reader, revision, scope, proof, file);
            }
            assertReadOnly(reader);
            reader.rollback();
            write(directory.resolve("SCHEMA-SNAPSHOT.json"), snapshot);
            if (export.historyJson() != null) {
                write(directory.resolve("MIGRATION-HISTORY.json"), export.historyJson());
            }
            write(directory.resolve("status"), export.status().name() + "\n");
            return snapshot;
        }
    }

    private void rejectMismatchedCatalog(Connection reader, String revision, String scope, AppliedArtifact proof,
            Path file) throws SQLException {
        try {
            FlywayHistoryCollector.collectMySql(reader, revision, scope, "missing_catalog", proof, file);
        } catch (SQLException failure) {
            check(failure.getCause() == null && failure.getNextException() == null);
            return;
        }
        throw new SQLException("Unexpected acceptance of a mismatched MySQL catalog");
    }

    private void configureReader(Connection reader) throws SQLException {
        reader.setReadOnly(true);
        reader.setAutoCommit(false);
        assertReadOnly(reader);
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

    private static String digest(Path file) throws Exception {
        return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(Files.readAllBytes(file)));
    }

    private static void write(Path file, String value) throws Exception {
        Files.writeString(file, value, StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE);
    }

    private void check(boolean condition) throws SQLException {
        if (!condition) throw new SQLException("MySQL Flyway fixture assertion failed");
        assertions++;
    }
}
