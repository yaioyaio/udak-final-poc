package dev.udak.schema;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.sql.Connection;
import java.sql.SQLException;
import java.util.HexFormat;
import java.util.Objects;
import java.util.regex.Pattern;

/** Exports at most one provenance-verified Flyway SQL history row from PostgreSQL. */
public final class FlywayHistoryCollector {
    private static final String HISTORY = "flyway_schema_history";
    private static final int MAX_SQL_BYTES = 1024 * 1024;
    private static final Pattern IDENTIFIER = Pattern.compile("[a-z][a-z0-9_]{0,62}");
    private static final Pattern REVISION = Pattern.compile("[a-f0-9]{40}(?:[a-f0-9]{24})?");
    private static final Pattern SHA256 = Pattern.compile("[a-f0-9]{64}");
    private static final Pattern VERSION = Pattern.compile("[0-9]{1,9}");
    private static final Pattern SCRIPT = Pattern.compile("V[A-Za-z0-9_-]{1,120}\\.sql");

    public enum Status { VERIFIED, EMPTY, HISTORY_FILE_UNVERIFIED, UNSUPPORTED_HISTORY }

    /** Trusted, apply-time evidence for the caller-selected deployment. */
    public record AppliedArtifact(String catalog, String schema, int rank, String version, String script,
                                  int flywayChecksum, String sha256) {}

    public record Export(Status status, String historyJson) {}

    private FlywayHistoryCollector() {}

    /**
     * Uses the caller's read-only transaction. The artifact proof must come from the same trusted
     * deployment that applied the reviewed bytes. A current file or a Flyway CRC32 cannot supply that proof.
     */
    public static Export collect(Connection connection, String revision, String scope, String schema,
                                 AppliedArtifact artifact, Path reviewedFile) throws SQLException {
        try {
            if (!matches(IDENTIFIER, schema) || !matches(REVISION, revision) || !matches(SHA256, scope)
                    || !connection.isReadOnly() || connection.getAutoCommit()) {
                throw new SQLException("Invalid Flyway history collection scope or transaction");
            }
            var metadata = connection.getMetaData();
            if (!"PostgreSQL".equals(metadata.getDatabaseProductName()) || !"\\".equals(metadata.getSearchStringEscape())) {
                throw new SQLException("Unsupported Flyway history source");
            }
            String catalog = connection.getCatalog();
            String schemaPattern = schema.replace("_", "\\_");
            try (var tables = metadata.getTables(catalog, schemaPattern, "flyway\\_schema\\_history",
                    new String[]{"TABLE"})) {
                if (!tables.next()) {
                    return empty(revision, scope);
                }
                if (!Objects.equals(catalog, tables.getString("TABLE_CAT"))
                        || !schema.equals(tables.getString("TABLE_SCHEM"))
                        || !HISTORY.equals(tables.getString("TABLE_NAME")) || tables.next()) {
                    return new Export(Status.UNSUPPORTED_HISTORY, null);
                }
            }
            try (var statement = connection.createStatement(); var rows = statement.executeQuery(
                    "SELECT installed_rank, version, script, checksum, type, success FROM \"" + schema
                            + "\".flyway_schema_history ORDER BY installed_rank LIMIT 2")) {
                if (!rows.next()) {
                    return empty(revision, scope);
                }
                int rank = rows.getInt("installed_rank");
                String version = rows.getString("version");
                String script = rows.getString("script");
                Integer crc = rows.getObject("checksum", Integer.class);
                if (rank <= 0 || !matches(VERSION, version) || Integer.parseInt(version) == 0
                        || !matches(SCRIPT, script) || crc == null
                        || !"SQL".equals(rows.getString("type")) || !rows.getBoolean("success") || rows.next()) {
                    return new Export(Status.UNSUPPORTED_HISTORY, null);
                }
                if (artifact == null || !Objects.equals(catalog, artifact.catalog()) || !schema.equals(artifact.schema())
                        || rank != artifact.rank() || !version.equals(artifact.version()) || !script.equals(artifact.script())
                        || crc != artifact.flywayChecksum() || !verifiedFile(reviewedFile, artifact)) {
                    return new Export(Status.HISTORY_FILE_UNVERIFIED, null);
                }
                String row = "{\"version\":\"" + Integer.parseInt(version) + "\",\"checksum_sha256\":\""
                        + artifact.sha256() + "\"}";
                return new Export(Status.VERIFIED, json(revision, scope, row));
            }
        } catch (SQLException | RuntimeException failure) {
            throw new SQLException("Flyway history collection failed");
        }
    }

    private static Export empty(String revision, String scope) {
        return new Export(Status.EMPTY, json(revision, scope, ""));
    }

    private static String json(String revision, String scope, String row) {
        return "{\"schema_version\":1,\"revision\":\"" + revision + "\",\"scope\":\"" + scope
                + "\",\"migrations\":[" + row + "]}\n";
    }

    private static boolean verifiedFile(Path file, AppliedArtifact artifact) {
        if (file == null || !matches(SHA256, artifact.sha256()) || !file.getFileName().toString().equals(artifact.script())
                || !Files.isRegularFile(file, LinkOption.NOFOLLOW_LINKS)) {
            return false;
        }
        try (var input = Files.newInputStream(file, LinkOption.NOFOLLOW_LINKS)) {
            byte[] bytes = input.readNBytes(MAX_SQL_BYTES + 1);
            return bytes.length <= MAX_SQL_BYTES && artifact.sha256().equals(sha256(bytes));
        } catch (IOException failure) {
            return false;
        }
    }

    private static boolean matches(Pattern pattern, String value) {
        return value != null && pattern.matcher(value).matches();
    }

    private static String sha256(byte[] bytes) {
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes));
        } catch (NoSuchAlgorithmException failure) {
            throw new IllegalStateException("SHA-256 is unavailable");
        }
    }
}
