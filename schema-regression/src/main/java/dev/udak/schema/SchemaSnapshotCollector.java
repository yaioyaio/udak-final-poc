package dev.udak.schema;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.sql.Connection;
import java.sql.DatabaseMetaData;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Types;
import java.util.HashSet;
import java.util.HexFormat;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.StringJoiner;
import java.util.TreeMap;
import java.util.regex.Pattern;

/** Collects the version 1 column contract for explicitly selected H2 tables. */
public final class SchemaSnapshotCollector {
    private static final String PRODUCT = "H2";
    private static final String FAILURE = "Schema snapshot collection failed";
    private static final Pattern LOGICAL_NAME = Pattern.compile("[a-z][a-z0-9_]{0,62}");
    private static final Pattern UPPERCASE_COLUMN = Pattern.compile("[A-Z][A-Z0-9_]{0,62}");
    private static final Pattern PHYSICAL_NAME = Pattern.compile("[A-Za-z][A-Za-z0-9_%]{0,62}");
    private static final Pattern REVISION = Pattern.compile("[a-f0-9]{40}(?:[a-f0-9]{24})?");
    private static final int MAX_TABLES = 128;
    private static final int MAX_COLUMNS = 4096;
    private static final int MAX_WIDTH = 100_000;

    private SchemaSnapshotCollector() {}

    /**
     * Returns a normalized JSON snapshot for the logical-to-physical table mapping in one catalog and schema.
     * The connection stays caller-owned. JDBC errors and invalid metadata return a generic SQL exception.
     */
    public static String collect(Connection connection, String revision, String catalog, String schema,
                                 Map<String, String> tables) throws SQLException {
        try {
            require(connection != null && matches(REVISION, revision));
            require(matches(PHYSICAL_NAME, catalog) && matches(PHYSICAL_NAME, schema));
            var selected = validateTables(tables);
            DatabaseMetaData metadata = connection.getMetaData();
            require(PRODUCT.equals(metadata.getDatabaseProductName()));
            String escape = metadata.getSearchStringEscape();
            require("\\".equals(escape));
            boolean foldsToUppercase = metadata.storesUpperCaseIdentifiers();

            StringJoiner rows = new StringJoiner(",");
            int remainingColumns = MAX_COLUMNS;
            for (var table : selected.entrySet()) {
                Map<String, Column> columns = readColumns(
                        metadata, catalog, schema, table.getValue(), escape, foldsToUppercase, remainingColumns);
                for (var column : columns.entrySet()) {
                    rows.add(column.getValue().json(table.getKey(), column.getKey()));
                }
                remainingColumns -= columns.size();
            }
            String scope = scope(selected.keySet());
            return "{\"schema_version\":1,\"revision\":\"" + revision + "\",\"scope\":\"" + scope
                    + "\",\"columns\":[" + rows + "]}\n";
        } catch (SQLException | RuntimeException failure) {
            throw new SQLException(FAILURE);
        }
    }

    private static Map<String, String> validateTables(Map<String, String> tables) throws SQLException {
        require(tables != null && !tables.isEmpty() && tables.size() <= MAX_TABLES);
        Map<String, String> selected = new TreeMap<>();
        Set<String> physicalNames = new HashSet<>();
        for (var table : tables.entrySet()) {
            String logical = table.getKey();
            String physical = table.getValue();
            require(matches(LOGICAL_NAME, logical) && matches(PHYSICAL_NAME, physical));
            require(selected.size() < MAX_TABLES && physicalNames.add(physical));
            require(selected.putIfAbsent(logical, physical) == null);
        }
        require(!selected.isEmpty());
        return selected;
    }

    private static Map<String, Column> readColumns(DatabaseMetaData metadata, String catalog, String schema,
                                                   String table, String escape, boolean foldsToUppercase,
                                                   int remaining) throws SQLException {
        Map<String, Column> columns = new TreeMap<>();
        try (ResultSet rows = metadata.getColumns(catalog, literalPattern(schema, escape),
                literalPattern(table, escape), "%")) {
            while (rows.next()) {
                require(columns.size() < remaining);
                require(catalog.equals(rows.getString("TABLE_CAT"))
                        && schema.equals(rows.getString("TABLE_SCHEM"))
                        && table.equals(rows.getString("TABLE_NAME")));
                String name = rows.getString("COLUMN_NAME");
                require(matches(foldsToUppercase ? UPPERCASE_COLUMN : LOGICAL_NAME, name));
                String logicalName = name.toLowerCase(Locale.ROOT);
                int jdbcType = rows.getInt("DATA_TYPE");
                require(!rows.wasNull());
                String type = normalizedType(jdbcType);
                int width = 0;
                if ("VARCHAR".equals(type)) {
                    width = rows.getInt("COLUMN_SIZE");
                    require(!rows.wasNull() && width > 0 && width <= MAX_WIDTH);
                }
                int nullable = rows.getInt("NULLABLE");
                require(!rows.wasNull() && (nullable == DatabaseMetaData.columnNoNulls
                        || nullable == DatabaseMetaData.columnNullable));
                require(columns.putIfAbsent(logicalName, new Column(type, width,
                        nullable == DatabaseMetaData.columnNullable)) == null);
            }
        }
        require(!columns.isEmpty());
        return columns;
    }

    private static String normalizedType(int type) throws SQLException {
        return switch (type) {
            case Types.INTEGER -> "INTEGER";
            case Types.BIGINT -> "BIGINT";
            case Types.VARCHAR -> "VARCHAR";
            case Types.DECIMAL, Types.NUMERIC -> "DECIMAL";
            case Types.BOOLEAN -> "BOOLEAN";
            case Types.DATE -> "DATE";
            case Types.TIMESTAMP -> "TIMESTAMP";
            case Types.LONGVARCHAR -> "TEXT";
            default -> throw new SQLException(FAILURE);
        };
    }

    private static String literalPattern(String name, String escape) {
        return name.replace("_", escape + "_").replace("%", escape + "%");
    }

    private static boolean matches(Pattern pattern, String value) {
        return value != null && pattern.matcher(value).matches();
    }

    private static void require(boolean valid) throws SQLException {
        if (!valid) throw new SQLException(FAILURE);
    }

    private static String scope(Set<String> logicalTables) {
        String payload = "udak-schema-contract-v1\n" + PRODUCT + "\n" + String.join("\n", logicalTables) + "\n";
        try {
            byte[] digest = MessageDigest.getInstance("SHA-256").digest(payload.getBytes(StandardCharsets.UTF_8));
            return HexFormat.of().formatHex(digest);
        } catch (NoSuchAlgorithmException failure) {
            throw new IllegalStateException(FAILURE);
        }
    }

    private record Column(String type, int width, boolean nullable) {
        String json(String table, String name) {
            return "{\"table\":\"" + table + "\",\"column\":\"" + name + "\",\"type\":\"" + type
                    + "\",\"width\":" + width + ",\"nullable\":" + nullable + "}";
        }
    }
}
