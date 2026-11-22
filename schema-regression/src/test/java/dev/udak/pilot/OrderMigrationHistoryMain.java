package dev.udak.pilot;

import dev.udak.schema.SchemaSnapshotCollector;
import java.io.OutputStream;
import java.io.PrintStream;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.security.MessageDigest;
import java.util.HexFormat;
import java.util.List;
import java.util.Map;
import java.util.regex.Pattern;
import org.springframework.jdbc.core.JdbcTemplate;

/** Captures isolated H2 schema snapshots and the migration rows visible in each database. */
public final class OrderMigrationHistoryMain {
    private static final Map<String, String> TABLES = Map.of(
            "order_audit", "ORDER_AUDIT", "order_stock", "ORDER_STOCK", "placed_order", "PLACED_ORDER");
    private static final Pattern SCOPE = Pattern.compile("\"scope\":\"([a-f0-9]{64})\"");
    private static final String VERSION = "2";
    private static final int MAX_MIGRATION_BYTES = 1024;
    private final OrderFixture.Checks checks = new OrderFixture.Checks();

    public static void main(String[] args) {
        PrintStream output = System.out;
        PrintStream errors = System.err;
        var fixture = new OrderMigrationHistoryMain();
        try (var discard = new PrintStream(OutputStream.nullOutputStream())) {
            System.setOut(discard);
            System.setErr(discard);
            if (args.length != 2) {
                throw new IllegalArgumentException();
            }
            fixture.capture(Path.of(args[0]), Path.of(args[1]));
        } catch (Exception | AssertionError | LinkageError failure) {
            output.println("ORDER_MIGRATION_HISTORY FAIL");
            output.println("CATEGORY=" + failure.getClass().getSimpleName());
            if (failure instanceof AssertionError assertion && assertion.getMessage() != null
                    && assertion.getMessage().matches("[A-Z][A-Z_]{0,48}")) {
                output.println("CHECK=" + assertion.getMessage());
            }
            System.exit(1);
        } finally {
            System.setOut(output);
            System.setErr(errors);
        }
        output.println("ORDER_MIGRATION_HISTORY PASS");
        output.println("ASSERTIONS=" + fixture.checks.count());
    }

    private void capture(Path workspace, Path migrationPath) throws Exception {
        checks.require(migrationPath.isAbsolute() && Files.isRegularFile(migrationPath, LinkOption.NOFOLLOW_LINKS)
                && "V002-WIDEN-AUDIT-EVENT-CODE.sql".equals(migrationPath.getFileName().toString()), "MIGRATION_FILE");
        byte[] migration;
        try (var input = Files.newInputStream(migrationPath, LinkOption.NOFOLLOW_LINKS)) {
            migration = input.readNBytes(MAX_MIGRATION_BYTES + 1);
        }
        checks.require(migration.length > 0 && migration.length <= MAX_MIGRATION_BYTES, "MIGRATION_SIZE");
        String sql = StandardCharsets.UTF_8.newDecoder().decode(ByteBuffer.wrap(migration)).toString();
        String checksum = HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(migration));
        for (Variant variant : Variant.values()) {
            captureVariant(workspace, variant, sql, checksum);
        }
    }

    private void captureVariant(Path workspace, Variant variant, String migrationSql, String checksum) throws Exception {
        var source = OrderFixture.createDataSource();
        var jdbc = new JdbcTemplate(source);
        jdbc.setQueryTimeout(5);
        jdbc.execute("ALTER TABLE order_audit ADD COLUMN fixture_note VARCHAR(16)");
        jdbc.execute("""
                CREATE TABLE fixture_migration_history (
                    migration_version VARCHAR(16) PRIMARY KEY,
                    checksum_sha256 VARCHAR(64) NOT NULL
                )
                """);
        if (variant != Variant.BASE) {
            jdbc.execute(migrationSql);
            if (variant != Variant.MISSING) {
                checks.equal(1, jdbc.update("INSERT INTO fixture_migration_history VALUES (?, ?)", VERSION, checksum),
                        "MIGRATION_RECORDED");
            }
        }
        if (variant == Variant.UNRELATED) {
            jdbc.execute("ALTER TABLE order_audit ALTER COLUMN event_code SET DATA TYPE VARCHAR(16)");
            jdbc.execute("ALTER TABLE order_audit ALTER COLUMN fixture_note SET DATA TYPE VARCHAR(32)");
        }

        String snapshot;
        try (var connection = source.getConnection()) {
            snapshot = SchemaSnapshotCollector.collect(connection, variant.revision, connection.getCatalog(),
                    connection.getSchema(), TABLES);
        }
        var scope = SCOPE.matcher(snapshot);
        checks.require(scope.find(), "SCHEMA_SCOPE_PRESENT");
        List<Migration> history = jdbc.query("""
                SELECT migration_version, checksum_sha256 FROM fixture_migration_history ORDER BY migration_version
                """, (row, index) -> new Migration(row.getString(1), row.getString(2)));
        List<Migration> expected = variant == Variant.MATCHED || variant == Variant.UNRELATED
                ? List.of(new Migration(VERSION, checksum)) : List.of();
        checks.equal(expected, history, "MIGRATION_HISTORY");
        String migrations = history.isEmpty() ? "" : history.get(0).json();
        Path directory = workspace.resolve(variant.directory);
        save(directory.resolve("SCHEMA-SNAPSHOT.json"), snapshot);
        save(directory.resolve("MIGRATION-HISTORY.json"),
                "{\"schema_version\":1,\"revision\":\"" + variant.revision + "\",\"scope\":\"" + scope.group(1)
                        + "\",\"migrations\":[" + migrations + "]}\n");
    }

    private static void save(Path target, String contents) throws Exception {
        Files.writeString(target, contents, StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE);
    }

    private record Migration(String version, String checksum) {
        private String json() {
            return "{\"version\":\"" + version + "\",\"checksum_sha256\":\"" + checksum + "\"}";
        }
    }

    private enum Variant {
        BASE("history-base", "1"), MATCHED("history-matched", "2"),
        MISSING("history-missing", "2"), UNRELATED("history-unrelated", "3");

        private final String directory;
        private final String revision;

        Variant(String directory, String revisionDigit) {
            this.directory = directory;
            this.revision = revisionDigit.repeat(40);
        }
    }
}
