package dev.udak.schema;

import java.lang.reflect.InvocationHandler;
import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Method;
import java.lang.reflect.Proxy;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.sql.Connection;
import java.sql.DatabaseMetaData;
import java.sql.DriverManager;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.TreeMap;

/** Runs the collector against isolated embedded H2 schemas and exports fixed comparison inputs. */
public final class SchemaSnapshotCollectorContractTest {
    private static final String REVISION = "a".repeat(40);
    private static final String SCHEMA = "scope_one";
    private static final Map<String, String> SELECTION = Map.of("contract_item", "source_item");
    private static final String SANITIZED_FAILURE = "Schema snapshot collection failed";
    private static final String DRIVER_PRIVATE_MARKER = "fixture driver exception marker";
    private static final int QUERY_TIMEOUT_SECONDS = 5;

    private int assertions;

    public static void main(String[] args) {
        try {
            if (args.length != 3) throw new IllegalArgumentException();
            var test = new SchemaSnapshotCollectorContractTest();
            String baseline = test.fixture("baseline_env", false);
            String equal = test.fixture("equal_env", false);
            String drift = test.fixture("drift_env", true);
            test.check(baseline.equals(equal));
            test.check(!baseline.equals(drift));
            test.defaultIdentifierCasing();
            save(args[0], baseline);
            save(args[1], equal);
            save(args[2], drift);
            System.out.println("Schema snapshot collector contract checks: " + test.assertions);
        } catch (Exception | LinkageError failure) {
            System.err.println("Schema snapshot collector contract failed");
            System.exit(1);
        }
    }

    private void defaultIdentifierCasing() throws SQLException {
        try (Connection connection = DriverManager.getConnection("jdbc:h2:mem:default_case");
             var statement = connection.createStatement()) {
            statement.setQueryTimeout(QUERY_TIMEOUT_SECONDS);
            statement.executeUpdate("CREATE TABLE contract_item (item_code INTEGER NOT NULL)");
            statement.executeUpdate("CREATE TABLE mixed_item (\"Item_Code\" INTEGER NOT NULL)");
            String catalog = connection.getCatalog();
            String snapshot = collect(connection, catalog, "PUBLIC", Map.of("contract_item", "CONTRACT_ITEM"));
            check(snapshot.contains(column("item_code", "INTEGER", 0, false)));
            expectFailure(() -> collect(connection, catalog, "PUBLIC", Map.of("contract_item", "MIXED_ITEM")));
        }
    }

    private String fixture(String database, boolean drift) throws SQLException {
        try (Connection connection = DriverManager.getConnection("jdbc:h2:mem:" + database
                + ";DATABASE_TO_LOWER=TRUE")) {
            setup(connection, drift);
            String catalog = connection.getCatalog();
            connection.setAutoCommit(false);
            connection.setTransactionIsolation(Connection.TRANSACTION_SERIALIZABLE);
            Connection metadataOnly = metadataOnly(connection.getMetaData());
            String snapshot = collect(metadataOnly, catalog, SCHEMA, SELECTION);
            check(!connection.getAutoCommit());
            check(connection.getTransactionIsolation() == Connection.TRANSACTION_SERIALIZABLE);
            check(!connection.isClosed());
            check(snapshot.contains("\"revision\":\"" + REVISION + "\""));
            check(!snapshot.contains(database) && !snapshot.contains("source_item")
                    && !snapshot.contains(SCHEMA) && !snapshot.contains("decoy_col"));
            check(snapshot.endsWith("\n"));
            if (drift) {
                check(snapshot.contains(column("added_col", "DATE", 0, true)));
                check(!snapshot.contains("\"column\":\"legacy_col\""));
                check(snapshot.contains(column("quantity", "BIGINT", 0, false)));
                check(snapshot.contains(column("label", "VARCHAR", 64, true)));
                check(snapshot.contains(column("note", "VARCHAR", 16, true)));
            } else {
                check(snapshot.contains(column("legacy_col", "DATE", 0, true)));
                check(!snapshot.contains("\"column\":\"added_col\""));
                check(snapshot.contains(column("quantity", "INTEGER", 0, false)));
                check(snapshot.contains(column("label", "VARCHAR", 32, true)));
                check(snapshot.contains(column("note", "VARCHAR", 16, false)));
            }
            if ("baseline_env".equals(database)) invalidCases(connection, metadataOnly, catalog);
            connection.rollback();
            return snapshot;
        }
    }

    private static void setup(Connection connection, boolean drift) throws SQLException {
        try (var statement = connection.createStatement()) {
            statement.setQueryTimeout(QUERY_TIMEOUT_SECONDS);
            statement.executeUpdate("CREATE SCHEMA scope_one");
            statement.executeUpdate("CREATE SCHEMA scopexone");
            statement.executeUpdate("CREATE TABLE scopexone.source_item (decoy_col REAL)");
            statement.executeUpdate("CREATE TABLE scope_one.sourcexitem (decoy_col REAL)");
            statement.executeUpdate("CREATE TABLE scope_one.unsupported_item (field REAL)");
            statement.executeUpdate("CREATE TABLE scope_one.unbounded_item (field VARCHAR)");
            statement.executeUpdate("CREATE TABLE scope_one.\"rate%table\" (rate_col DECIMAL(8, 2))");
            statement.executeUpdate("CREATE TABLE scope_one.ratextable (decoy_col REAL)");
            if (drift) {
                statement.executeUpdate("CREATE TABLE scope_one.source_item (quantity BIGINT NOT NULL,"
                        + " label VARCHAR(64), note VARCHAR(16), added_col DATE)");
            } else {
                statement.executeUpdate("CREATE TABLE scope_one.source_item (quantity INTEGER NOT NULL,"
                        + " label VARCHAR(32), note VARCHAR(16) NOT NULL, legacy_col DATE)");
            }
        }
    }

    private void invalidCases(Connection source, Connection connection, String catalog) throws SQLException {
        var reversed = new LinkedHashMap<String, String>();
        reversed.put("rate_table", "rate%table");
        reversed.putAll(SELECTION);
        String multiple = collect(connection, catalog, SCHEMA, reversed);
        check(multiple.equals(collect(connection, catalog, SCHEMA, new TreeMap<>(reversed))));
        check(multiple.indexOf("\"table\":\"contract_item\"") < multiple.indexOf("\"table\":\"rate_table\""));
        check(multiple.contains("\"column\":\"rate_col\",\"type\":\"DECIMAL\",\"width\":0"));
        check(!multiple.contains("decoy_col"));
        expectFailure(() -> collect(connection, catalog, SCHEMA, Map.of()));
        expectFailure(() -> collect(connection, catalog, SCHEMA, Map.of("UPPER", "source_item")));
        expectFailure(() -> collect(connection, catalog, SCHEMA, Map.of("invalid_table", "source item")));
        expectFailure(() -> collect(connection, catalog, SCHEMA, Map.of("first", "source_item", "second", "source_item")));
        expectFailure(() -> collect(connection, catalog, SCHEMA, Map.of("missing_item", "missing_item")));
        expectFailure(() -> collect(connection, catalog, SCHEMA, Map.of("unsupported_item", "unsupported_item")));
        expectFailure(() -> collect(connection, catalog, SCHEMA, Map.of("unbounded_item", "unbounded_item")));
        expectFailure(() -> collect(connection, catalog, null, SELECTION));
        expectFailure(() -> collect(connection, "other_catalog", SCHEMA, SELECTION));
        expectFailure(() -> SchemaSnapshotCollector.collect(connection, "invalid", catalog, SCHEMA, SELECTION));

        var excessiveSelection = new TreeMap<String, String>();
        for (int number = 0; number < 129; number++) {
            String table = "table_" + number;
            excessiveSelection.put(table, table);
        }
        expectFailure(() -> collect(connection, catalog, SCHEMA, excessiveSelection));

        DatabaseMetaData metadata = source.getMetaData();
        DatabaseMetaData otherProduct = proxy(DatabaseMetaData.class, (ignored, method, args) -> {
            if ("getDatabaseProductName".equals(method.getName())) return "OTHER_DBMS";
            return invoke(metadata, method, args);
        });
        expectFailure(() -> collect(metadataOnly(otherProduct), catalog, SCHEMA, SELECTION));

        DatabaseMetaData failedRead = proxy(DatabaseMetaData.class, (ignored, method, args) -> {
            if ("getColumns".equals(method.getName())) throw new SQLException(DRIVER_PRIVATE_MARKER);
            return invoke(metadata, method, args);
        });
        expectFailure(() -> collect(metadataOnly(failedRead), catalog, SCHEMA, SELECTION));

        DatabaseMetaData unknownNullability = proxy(DatabaseMetaData.class, (ignored, method, args) -> {
            Object result = invoke(metadata, method, args);
            if (!"getColumns".equals(method.getName())) return result;
            return proxy(ResultSet.class, (row, access, fields) -> {
                if ("getInt".equals(access.getName()) && "NULLABLE".equals(fields[0])) {
                    return DatabaseMetaData.columnNullableUnknown;
                }
                return invoke(result, access, fields);
            });
        });
        expectFailure(() -> collect(metadataOnly(unknownNullability), catalog, SCHEMA, SELECTION));
    }

    private static String column(String name, String type, int width, boolean nullable) {
        return "{\"table\":\"contract_item\",\"column\":\"" + name + "\",\"type\":\"" + type
                + "\",\"width\":" + width + ",\"nullable\":" + nullable + "}";
    }

    private static String collect(Connection connection, String catalog, String schema, Map<String, String> selection)
            throws SQLException {
        return SchemaSnapshotCollector.collect(connection, REVISION, catalog, schema, selection);
    }

    private static Connection metadataOnly(DatabaseMetaData metadata) {
        return proxy(Connection.class, (ignored, method, args) -> {
            if ("getMetaData".equals(method.getName())) return metadata;
            throw new IllegalStateException("Unexpected connection operation");
        });
    }

    private static <T> T proxy(Class<T> type, InvocationHandler handler) {
        return type.cast(Proxy.newProxyInstance(type.getClassLoader(), new Class<?>[]{type}, handler));
    }

    private static Object invoke(Object target, Method method, Object[] arguments) throws Throwable {
        try {
            return method.invoke(target, arguments);
        } catch (InvocationTargetException failure) {
            throw failure.getCause();
        }
    }

    private static void save(String name, String snapshot) throws java.io.IOException {
        Files.writeString(Path.of(name), snapshot, StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE);
    }

    private void expectFailure(Probe operation) throws SQLException {
        try {
            operation.run();
        } catch (SQLException failure) {
            check(SANITIZED_FAILURE.equals(failure.getMessage())
                    && failure.getCause() == null && failure.getNextException() == null);
            return;
        }
        throw new SQLException("Expected collector rejection");
    }

    private void check(boolean condition) throws SQLException {
        if (!condition) throw new SQLException("Collector contract assertion failed");
        assertions++;
    }

    @FunctionalInterface
    private interface Probe {
        void run() throws SQLException;
    }
}
