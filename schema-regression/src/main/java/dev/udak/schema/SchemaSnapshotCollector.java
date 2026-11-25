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
import java.util.Objects;
import java.util.Set;
import java.util.StringJoiner;
import java.util.TreeMap;
import java.util.regex.Pattern;

/** Collects the version 1 column contract for explicitly selected H2, PostgreSQL and MySQL tables. */
public final class SchemaSnapshotCollector {
    private static final String POSTGRESQL = "POSTGRESQL";
    private static final String MYSQL = "MYSQL";
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
     * MySQL uses the database as a JDBC catalog and requires a null schema.
     * The connection stays caller-owned. JDBC errors and invalid metadata return a generic SQL exception.
     */
    public static String collect(Connection connection, String revision, String catalog, String schema,
                                 Map<String, String> tables) throws SQLException {
        try {
            require(connection != null && matches(REVISION, revision));
            require(matches(PHYSICAL_NAME, catalog) && (schema == null || matches(PHYSICAL_NAME, schema)));
            var selected = validateTables(tables);
            DatabaseMetaData metadata = connection.getMetaData();
            String product = switch (metadata.getDatabaseProductName()) {
                case "H2" -> "H2";
                case "PostgreSQL" -> POSTGRESQL;
                case "MySQL" -> MYSQL;
                default -> throw new SQLException(FAILURE);
            };
            require(MYSQL.equals(product) == (schema == null));
            String escape = metadata.getSearchStringEscape();
            require("\\".equals(escape));
            boolean foldsToUppercase = metadata.storesUpperCaseIdentifiers();
            String[] tableTypes = switch (product) {
                case POSTGRESQL -> new String[]{"TABLE", "PARTITIONED TABLE"};
                case MYSQL -> new String[]{"TABLE"};
                default -> null;
            };
            StringJoiner rows = new StringJoiner(",");
            int remainingColumns = MAX_COLUMNS;
            for (var table : selected.entrySet()) {
                if (tableTypes != null) {
                    requireTable(metadata, catalog, schema, table.getValue(), escape, tableTypes);
                }
                Map<String, Column> columns = readColumns(metadata, catalog, schema, table.getValue(), escape,
                        foldsToUppercase, remainingColumns, product);
                for (var column : columns.entrySet()) {
                    rows.add(column.getValue().json(table.getKey(), column.getKey()));
                }
                remainingColumns -= columns.size();
            }
            String scope = scope(product, selected.keySet());
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

    private static void requireTable(DatabaseMetaData metadata, String catalog, String schema, String table,
                                     String escape, String[] types) throws SQLException {
        try (ResultSet rows = metadata.getTables(catalog, schemaPattern(schema, escape),
                literalPattern(table, escape), types)) {
            require(rows.next() && sameTable(rows, catalog, schema, table));
            if (schema == null) {
                require("TABLE".equals(rows.getString("TABLE_TYPE")));
            }
            require(!rows.next());
        }
    }

    private static boolean sameTable(ResultSet row, String catalog, String schema, String table) throws SQLException {
        return catalog.equals(row.getString("TABLE_CAT"))
                && Objects.equals(schema, row.getString("TABLE_SCHEM"))
                && table.equals(row.getString("TABLE_NAME"));
    }

    private static Map<String, Column> readColumns(DatabaseMetaData metadata, String catalog, String schema,
                                                   String table, String escape, boolean foldsToUppercase,
                                                   int remaining, String product) throws SQLException {
        Map<String, Column> columns = new TreeMap<>();
        try (ResultSet rows = metadata.getColumns(catalog, schemaPattern(schema, escape),
                literalPattern(table, escape), "%")) {
            while (rows.next()) {
                require(columns.size() < remaining);
                require(sameTable(rows, catalog, schema, table));
                String name = rows.getString("COLUMN_NAME");
                require(matches(foldsToUppercase ? UPPERCASE_COLUMN : LOGICAL_NAME, name));
                String logicalName = name.toLowerCase(Locale.ROOT);
                int jdbcType = rows.getInt("DATA_TYPE");
                require(!rows.wasNull());
                String type = switch (product) {
                    case POSTGRESQL -> postgresType(jdbcType, rows.getString("TYPE_NAME"));
                    case MYSQL -> mysqlType(jdbcType, rows.getString("TYPE_NAME"));
                    default -> normalizedType(jdbcType);
                };
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

    private static String postgresType(int jdbcType, String name) throws SQLException {
        // PgJDBC shares codes across distinct PostgreSQL types, e.g. TIMESTAMP and TIMESTAMPTZ.
        String type = switch (name) {
            case "int4", "serial" -> jdbcType == Types.INTEGER ? "INTEGER" : null;
            case "int8", "bigserial" -> jdbcType == Types.BIGINT ? "BIGINT" : null;
            case "varchar" -> jdbcType == Types.VARCHAR ? "VARCHAR" : null;
            case "numeric" -> jdbcType == Types.NUMERIC ? "DECIMAL" : null;
            case "bool" -> jdbcType == Types.BIT ? "BOOLEAN" : null;
            case "date" -> jdbcType == Types.DATE ? "DATE" : null;
            case "timestamp" -> jdbcType == Types.TIMESTAMP ? "TIMESTAMP" : null;
            case "text" -> jdbcType == Types.VARCHAR ? "TEXT" : null;
            case "uuid" -> jdbcType == Types.OTHER ? "UUID" : null;
            default -> null;
        };
        require(type != null);
        return type;
    }

    private static String mysqlType(int jdbcType, String name) throws SQLException {
        // Connector/J reuses JDBC codes across distinct types, including DATETIME and TIMESTAMP.
        String type = switch (name) {
            case "INT" -> jdbcType == Types.INTEGER ? "INTEGER" : null;
            case "BIGINT" -> jdbcType == Types.BIGINT ? "BIGINT" : null;
            case "VARCHAR" -> jdbcType == Types.VARCHAR ? "VARCHAR" : null;
            case "DECIMAL" -> jdbcType == Types.DECIMAL ? "DECIMAL" : null;
            case "DATE" -> jdbcType == Types.DATE ? "DATE" : null;
            case "TIMESTAMP" -> jdbcType == Types.TIMESTAMP ? "TIMESTAMP" : null;
            case "TEXT" -> jdbcType == Types.LONGVARCHAR ? "TEXT" : null;
            default -> null;
        };
        require(type != null);
        return type;
    }

    private static String schemaPattern(String schema, String escape) {
        return schema == null ? null : literalPattern(schema, escape);
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

    private static String scope(String product, Set<String> logicalTables) {
        String payload = "udak-schema-contract-v1\n" + product + "\n" + String.join("\n", logicalTables) + "\n";
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
