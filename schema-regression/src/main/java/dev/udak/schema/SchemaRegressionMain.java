package dev.udak.schema;

import dev.udak.inventory.InventoryCapture;
import dev.udak.observe.Framework;

import java.io.IOException;
import java.io.OutputStream;
import java.io.PrintStream;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.sql.Connection;
import java.sql.DatabaseMetaData;
import java.sql.DriverManager;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.ResultSetMetaData;
import java.sql.SQLException;
import java.sql.Statement;
import java.sql.Types;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashSet;
import java.util.HexFormat;
import java.util.List;
import java.util.Objects;
import java.util.Properties;
import java.util.Set;
import java.util.logging.LogManager;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.stream.Collectors;

/** Runs the bounded JDBC fixture through the private schema regression runner. */
public final class SchemaRegressionMain {
    private static final String BASE_REVISION = "1".repeat(40);
    private static final String HEAD_REVISION = "2".repeat(40);
    private static final String SCOPE = sha256("udak-schema-regression-scope-v1");
    private static final String SNAPSHOT = "SCHEMA-SNAPSHOT.json";
    private static final int TIMEOUT_SECONDS = 5;
    private static final int BASE_WIDTH = 32;
    private static final int HEAD_WIDTH = 64;
    private static final Row NULL_ROW = new Row(1, null);
    private static final Row UNICODE_ROW = new Row(2, "\uD55C\uAE00 \u00E9");
    private static final Row TEXT_ROW = new Row(3, "fixture label");
    private static final List<Row> EXPECTED_ROWS = List.of(NULL_ROW, UNICODE_ROW, TEXT_ROW);
    private static final Pattern SERVER_RELEASE = Pattern.compile(
            "([0-9]{1,3}(?:\\.[0-9]{1,4}){1,3})(?:[ -][ -~]*)?");

    private SchemaRegressionMain() {}

    public static void main(String[] args) {
        PrintStream report = System.out;
        PrintStream discard = new PrintStream(OutputStream.nullOutputStream());
        System.setOut(discard);
        System.setErr(discard);
        LogManager.getLogManager().reset();

        Mode mode = null;
        Stage stage = Stage.ARGUMENTS;
        try {
            Run run = Run.parse(args);
            mode = run.mode();
            stage = Stage.INPUT;
            String password = readPassword();
            stage = Stage.CONNECT;
            Identity identity;
            List<String> proofs = new ArrayList<>();
            try (Connection connection = connect(run, password)) {
                stage = Stage.IDENTITY;
                identity = identity(connection, run.engine());
                if (mode == Mode.PREPARE) {
                    stage = Stage.FIXTURE;
                    prepareFixture(connection, run.engine());
                } else {
                    stage = Stage.READ_ONLY;
                    connection.setReadOnly(true);
                    connection.setAutoCommit(false);
                }
                stage = Stage.SNAPSHOT;
                String base = snapshot(connection, run.engine(), Table.BASE, BASE_WIDTH, BASE_REVISION);
                String head = snapshot(connection, run.engine(), Table.HEAD, HEAD_WIDTH, HEAD_REVISION);
                if (mode == Mode.PREPARE) {
                    stage = Stage.ARTIFACTS;
                    writeArtifacts(run, base, head);
                } else {
                    stage = Stage.ARTIFACTS;
                    verifySnapshot(run.base(), base);
                    verifySnapshot(run.head(), head);
                    stage = Stage.QUERY;
                    for (Query query : run.queries()) proofs.add(verifyQuery(connection, run.engine(), query));
                    connection.rollback();
                }
                stage = Stage.CLOSE;
            }
            report.println(mode.name() + " PASS");
            report.println("SERVER_VERSION=" + identity.serverVersion());
            report.println("DRIVER_VERSION=" + identity.driverVersion());
            report.println("SERVER_RELEASE_SHA256=" + identity.serverReleaseHash());
            report.println("DRIVER_RELEASE_SHA256=" + identity.driverReleaseHash());
            proofs.forEach(report::println);
        } catch (Exception | LinkageError failure) {
            String action = mode == null ? "INPUT" : mode.name();
            report.println(action + " FAIL " + stage + " " + failureClass(failure));
            System.exit(1);
        }
    }

    private static String failureClass(Throwable failure) {
        if (failure instanceof IllegalArgumentException) return "IllegalArgumentException";
        if (failure instanceof FixtureFailure) return "FixtureFailure";
        if (failure instanceof SQLException) return "SQLException";
        if (failure instanceof IOException) return "IOException";
        if (failure instanceof ClassNotFoundException) return "ClassNotFoundException";
        if (failure instanceof LinkageError) return "LinkageError";
        return "ExecutionException";
    }

    private static String readPassword() throws IOException, FixtureFailure {
        byte[] bytes = System.in.readNBytes(130);
        try {
            int length = bytes.length - 1;
            require(length > 0 && length <= 128 && bytes[length] == '\n');
            for (int index = 0; index < length; index++) {
                require(bytes[index] >= 32 && bytes[index] <= 126);
            }
            return new String(bytes, 0, length, StandardCharsets.US_ASCII);
        } finally {
            Arrays.fill(bytes, (byte) 0);
        }
    }

    private static Connection connect(Run run, String password) throws SQLException, ClassNotFoundException,
            FixtureFailure {
        Engine engine = run.engine();
        Class.forName(engine.driverClass);
        Properties properties = engine.connectionProperties();
        properties.setProperty("user", "udak_fixture");
        properties.setProperty("password", password);
        String url = "jdbc:" + engine.protocol + "://127.0.0.1:" + run.port() + "/" + engine.database;
        DriverManager.setLoginTimeout(TIMEOUT_SECONDS);
        try {
            require(DriverManager.getDriver(url).getClass().getName().equals(engine.driverClass));
            return DriverManager.getConnection(url, properties);
        } finally {
            properties.remove("password");
        }
    }

    private static Identity identity(Connection connection, Engine engine) throws SQLException, FixtureFailure {
        DatabaseMetaData metadata = connection.getMetaData();
        require(engine.database.equals(connection.getCatalog()));
        if (engine.schema != null) require(engine.schema.equals(connection.getSchema()));
        require(engine.productName.equalsIgnoreCase(metadata.getDatabaseProductName()));
        require(engine.driverName.equalsIgnoreCase(metadata.getDriverName()));
        String serverRelease = metadata.getDatabaseProductVersion();
        String driverRelease = metadata.getDriverVersion();
        require(serverRelease != null && serverRelease.length() <= 256);
        require(driverRelease != null && driverRelease.length() <= 256);
        String serverVersion = extractVersion(SERVER_RELEASE, serverRelease);
        String driverVersion = extractVersion(engine.driverRelease, driverRelease);
        String[] serverParts = serverVersion.split("\\.");
        require(Integer.parseInt(serverParts[0]) == metadata.getDatabaseMajorVersion());
        require(Integer.parseInt(serverParts[1]) == metadata.getDatabaseMinorVersion());
        require(engine.expectedDriverVersion.equals(driverVersion));
        return new Identity(serverVersion, driverVersion, sha256(serverRelease), sha256(driverRelease));
    }

    private static String extractVersion(Pattern format, String release) throws FixtureFailure {
        Matcher match = format.matcher(release);
        require(match.matches());
        return match.group(1);
    }

    private static void prepareFixture(Connection connection, Engine engine) throws SQLException, FixtureFailure {
        for (Table table : Table.values()) {
            String qualified = engine.qualify(table);
            ddl(connection, engine.createFixture(table));
            try (PreparedStatement insert = connection.prepareStatement(
                    "INSERT INTO " + qualified + " (id, label) VALUES (?, ?)")) {
                insert.setQueryTimeout(TIMEOUT_SECONDS);
                // Descending IDs exercise the SELECT's ascending order independently of insertion order.
                insert(insert, TEXT_ROW);
                insert(insert, UNICODE_ROW);
                insert(insert, NULL_ROW);
            }
        }
        readColumns(connection, engine, Table.HEAD, BASE_WIDTH);
        ddl(connection, engine.widenLabel());
    }

    private static void ddl(Connection connection, String sql) throws SQLException {
        try (Statement statement = connection.createStatement()) {
            statement.setQueryTimeout(TIMEOUT_SECONDS);
            statement.executeUpdate(sql);
        }
    }

    private static void insert(PreparedStatement insert, Row row) throws SQLException, FixtureFailure {
        insert.setInt(1, row.id());
        if (row.label() == null) {
            insert.setNull(2, Types.VARCHAR);
        } else {
            insert.setString(2, row.label());
        }
        require(insert.executeUpdate() == 1);
    }

    private static String snapshot(Connection connection, Engine engine, Table table, int width, String revision)
            throws SQLException, FixtureFailure {
        List<Column> columns = readColumns(connection, engine, table, width);
        String body = columns.stream().map(Column::json).collect(Collectors.joining(","));
        return "{\"schema_version\":1,\"revision\":\"" + revision + "\",\"scope\":\"" + SCOPE
                + "\",\"columns\":[" + body + "]}\n";
    }

    private static List<Column> readColumns(Connection connection, Engine engine, Table table, int width)
            throws SQLException, FixtureFailure {
        DatabaseMetaData metadata = connection.getMetaData();
        String escape = metadata.getSearchStringEscape();
        require("\\".equals(escape));
        String pattern = table.identifier.replace("_", escape + "_");
        List<Column> columns = new ArrayList<>(2);
        try (ResultSet rows = metadata.getColumns(engine.database, engine.schema, pattern, "%")) {
            while (rows.next()) {
                require(columns.size() < 2);
                require(engine.database.equals(rows.getString("TABLE_CAT")));
                require(Objects.equals(engine.schema, rows.getString("TABLE_SCHEM")));
                require(table.identifier.equals(rows.getString("TABLE_NAME")));
                int position = rows.getInt("ORDINAL_POSITION");
                require(position == columns.size() + 1);
                int type = rows.getInt("DATA_TYPE");
                int nullable = rows.getInt("NULLABLE");
                require(!rows.wasNull());
                String column = rows.getString("COLUMN_NAME");
                if (position == 1) {
                    require("id".equals(column) && type == Types.INTEGER && nullable == DatabaseMetaData.columnNoNulls);
                    columns.add(new Column(column, "INTEGER", 0, false));
                } else {
                    require("label".equals(column) && type == Types.VARCHAR && nullable == DatabaseMetaData.columnNullable);
                    int actualWidth = rows.getInt("COLUMN_SIZE");
                    require(!rows.wasNull() && actualWidth == width);
                    columns.add(new Column(column, "VARCHAR", actualWidth, true));
                }
            }
        }
        require(columns.size() == 2);
        return columns;
    }

    private static void writeArtifacts(Run run, String base, String head) throws IOException {
        InventoryCapture capture = new InventoryCapture();
        for (Query query : Query.values()) capture.declare(Framework.JDBC, query.queryId, query.testId);
        String dependencies = Arrays.stream(Query.values()).map(Query::dependencyJson).collect(Collectors.joining(","));
        String dependencyJson = "{\"schema_version\":1,\"revision\":\"" + HEAD_REVISION + "\",\"scope\":\"" + SCOPE
                + "\",\"dependencies\":[" + dependencies + "]}\n";

        writeNew(run.base().resolve(SNAPSHOT), base);
        writeNew(run.head().resolve(SNAPSHOT), head);
        writeNew(run.head().resolve("SQL-INVENTORY.json"), capture.snapshotJson(HEAD_REVISION, SCOPE) + "\n");
        writeNew(run.head().resolve("QUERY-DEPENDENCIES.json"), dependencyJson);
    }

    private static void writeNew(Path path, String content) throws IOException {
        Files.writeString(path, content, StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE);
    }

    private static void verifySnapshot(Path directory, String actual) throws IOException, FixtureFailure {
        Path path = directory.resolve(SNAPSHOT);
        require(Files.isRegularFile(path, LinkOption.NOFOLLOW_LINKS));
        byte[] expected = actual.getBytes(StandardCharsets.UTF_8);
        try (var source = Files.newInputStream(path, LinkOption.NOFOLLOW_LINKS)) {
            require(Arrays.equals(expected, source.readNBytes(expected.length + 1)));
        }
    }

    private static String verifyQuery(Connection connection, Engine engine, Query query)
            throws SQLException, FixtureFailure {
        CheckProof proof = new CheckProof(query);
        for (Invocation invocation : query.invocations) {
            proof.record(invocation.id());
            List<Row> original = select(connection, engine, Table.BASE, query, invocation, proof);
            List<Row> candidate = select(connection, engine, Table.HEAD, query, invocation, proof);
            proof.check(original.equals(invocation.expected()));
            proof.check(candidate.equals(invocation.expected()));
            proof.check(original.equals(candidate));
        }
        return "QUERY=" + query.queryHash + ":" + query.testHash + ":" + proof.assertions + ":" + proof.finish();
    }

    private static List<Row> select(Connection connection, Engine engine, Table table, Query query,
                                    Invocation invocation, CheckProof proof) throws SQLException, FixtureFailure {
        proof.record(table.name());
        List<Row> rows = new ArrayList<>();
        try (PreparedStatement select = connection.prepareStatement(query.sql.formatted(engine.qualify(table)))) {
            select.setQueryTimeout(TIMEOUT_SECONDS);
            select.setMaxRows(EXPECTED_ROWS.size() + 1);
            if (invocation.id() != null) select.setInt(1, invocation.id());
            try (ResultSet results = select.executeQuery()) {
                ResultSetMetaData metadata = results.getMetaData();
                proof.check(metadata.getColumnCount() == 2);
                checkColumn(metadata, 1, "id", Types.INTEGER, Integer.class, proof);
                checkColumn(metadata, 2, "label", Types.VARCHAR, String.class, proof);
                while (results.next()) {
                    proof.check(rows.size() < EXPECTED_ROWS.size());
                    Object id = results.getObject(1);
                    proof.check(id instanceof Integer && !results.wasNull());
                    Object label = results.getObject(2);
                    proof.check((label == null || label instanceof String) && results.wasNull() == (label == null));
                    proof.record(id);
                    proof.record(label);
                    rows.add(new Row((Integer) id, (String) label));
                }
            }
        }
        proof.record(rows.size());
        return rows;
    }

    private static void checkColumn(ResultSetMetaData metadata, int index, String expectedLabel,
                                    int expectedType, Class<?> expectedClass, CheckProof proof)
            throws SQLException, FixtureFailure {
        String label = metadata.getColumnLabel(index);
        int sqlType = metadata.getColumnType(index);
        String javaClass = metadata.getColumnClassName(index);
        proof.check(expectedLabel.equals(label));
        proof.check(expectedType == sqlType);
        proof.check(expectedClass.getName().equals(javaClass));
        proof.record(label);
        proof.record(sqlType);
        proof.record(javaClass);
    }

    private static void require(boolean valid) throws FixtureFailure {
        if (!valid) throw new FixtureFailure();
    }

    private static MessageDigest digest() {
        try {
            return MessageDigest.getInstance("SHA-256");
        } catch (NoSuchAlgorithmException unavailable) {
            throw new IllegalStateException();
        }
    }

    private static String sha256(String value) {
        return HexFormat.of().formatHex(digest().digest(value.getBytes(StandardCharsets.UTF_8)));
    }

    private enum Mode { PREPARE, VERIFY }

    private enum Stage { ARGUMENTS, INPUT, CONNECT, IDENTITY, FIXTURE, READ_ONLY, SNAPSHOT, ARTIFACTS, QUERY, CLOSE }

    private enum Table {
        BASE("udak_entry_base"), HEAD("udak_entry_head");

        private final String identifier;

        Table(String identifier) {
            this.identifier = identifier;
        }
    }

    private enum Engine {
        POSTGRESQL("postgresql", "postgres", "public", "PostgreSQL", "org.postgresql.Driver",
                "PostgreSQL JDBC Driver", "42.7.14", "([0-9]+(?:\\.[0-9]+){2})"),
        MYSQL("mysql", "udak_fixture", null, "MySQL", "com.mysql.cj.jdbc.Driver",
                "MySQL Connector/J", "26.10.0",
                "mysql-connector-j-([0-9]+(?:\\.[0-9]+){2}) \\(Revision: [A-Za-z0-9._-]{1,128}\\)");

        private final String protocol;
        private final String database;
        private final String schema;
        private final String productName;
        private final String driverClass;
        private final String driverName;
        private final String expectedDriverVersion;
        private final Pattern driverRelease;

        Engine(String protocol, String database, String schema, String productName, String driverClass,
               String driverName, String expectedDriverVersion, String driverRelease) {
            this.protocol = protocol;
            this.database = database;
            this.schema = schema;
            this.productName = productName;
            this.driverClass = driverClass;
            this.driverName = driverName;
            this.expectedDriverVersion = expectedDriverVersion;
            this.driverRelease = Pattern.compile(driverRelease);
        }

        String qualify(Table table) {
            return (schema == null ? database : schema) + "." + table.identifier;
        }

        String createFixture(Table table) {
            String ddl = "CREATE TABLE " + qualify(table) + " (id INTEGER PRIMARY KEY, label VARCHAR(" + BASE_WIDTH + "))";
            return this == MYSQL ? ddl + " DEFAULT CHARACTER SET utf8mb4" : ddl;
        }

        String widenLabel() {
            String prefix = "ALTER TABLE " + qualify(Table.HEAD) + " ";
            String type = "VARCHAR(" + HEAD_WIDTH + ")";
            return switch (this) {
                case POSTGRESQL -> prefix + "ALTER COLUMN label TYPE " + type;
                case MYSQL -> prefix + "MODIFY COLUMN label " + type + " NULL";
            };
        }

        Properties connectionProperties() {
            Properties properties = new Properties();
            switch (this) {
                case POSTGRESQL -> {
                    properties.setProperty("connectTimeout", "5");
                    properties.setProperty("socketTimeout", "5");
                    properties.setProperty("currentSchema", schema);
                    properties.setProperty("sslmode", "disable");
                    properties.setProperty("gssEncMode", "disable");
                    properties.setProperty("options", "-c statement_timeout=5000");
                }
                case MYSQL -> {
                    properties.setProperty("connectTimeout", "5000");
                    properties.setProperty("socketTimeout", "5000");
                    properties.setProperty("sslMode", "DISABLED");
                    properties.setProperty("allowPublicKeyRetrieval", "true");
                    properties.setProperty("logger", "com.mysql.cj.log.NullLogger");
                    properties.setProperty("databaseTerm", "CATALOG");
                    properties.setProperty("characterEncoding", "UTF-8");
                    properties.setProperty("useInformationSchema", "true");
                    properties.setProperty("sessionVariables",
                            "max_execution_time=5000,lock_wait_timeout=5,innodb_lock_wait_timeout=5");
                }
            }
            return properties;
        }
    }

    private enum Query {
        LABEL_BY_ID("schema.fixture.label-by-id", "SELECT id, label FROM %s WHERE id = ?",
                List.of("id", "label"), List.of(new Invocation(2, List.of(UNICODE_ROW)),
                new Invocation(1, List.of(NULL_ROW)), new Invocation(4, List.of()))),
        LABELS_ORDERED("schema.fixture.labels-ordered", "SELECT id, label FROM %s ORDER BY id",
                List.of("id", "label"), List.of(new Invocation(null, EXPECTED_ROWS))),
        IDS_ORDERED("schema.fixture.ids-ordered", "SELECT id FROM %s ORDER BY id", List.of("id"), List.of());

        private final String queryId;
        private final String testId;
        private final String queryHash;
        private final String testHash;
        private final String sql;
        private final List<String> columns;
        private final List<Invocation> invocations;

        Query(String queryId, String sql, List<String> columns, List<Invocation> invocations) {
            this.queryId = queryId;
            this.testId = queryId + ".regression";
            this.queryHash = InventoryCapture.hashQueryId(queryId);
            this.testHash = InventoryCapture.hashTestId(testId);
            this.sql = sql;
            this.columns = columns;
            this.invocations = invocations;
        }

        String dependencyJson() {
            String references = columns.stream().map(column -> "{\"table\":\"udak_entry\",\"column\":\"" + column + "\"}")
                    .collect(Collectors.joining(","));
            return "{\"framework\":\"JDBC\",\"query_id_hash\":\"" + queryHash + "\",\"columns\":[" + references + "]}";
        }
    }

    private record Run(Mode mode, Engine engine, int port, Path base, Path head, List<Query> queries) {
        static Run parse(String[] args) {
            if (args.length < 4 || args.length > 6 || !args[2].matches("[1-9][0-9]{0,4}")) {
                throw new IllegalArgumentException();
            }
            Mode mode = switch (args[0]) {
                case "prepare" -> Mode.PREPARE;
                case "verify" -> Mode.VERIFY;
                default -> throw new IllegalArgumentException();
            };
            int port = Integer.parseInt(args[2]);
            if (port > 65535 || (mode == Mode.PREPARE && args.length != 4)
                    || (mode == Mode.VERIFY && args.length == 4)) {
                throw new IllegalArgumentException();
            }
            Engine engine = Engine.valueOf(args[1]);
            Path work = Path.of(args[3]).toAbsolutePath().normalize();
            Path base = work.resolve("base");
            Path head = work.resolve("head");
            if (!Files.isDirectory(work, LinkOption.NOFOLLOW_LINKS)
                    || !Files.isDirectory(base, LinkOption.NOFOLLOW_LINKS)
                    || !Files.isDirectory(head, LinkOption.NOFOLLOW_LINKS)) {
                throw new IllegalArgumentException();
            }
            return new Run(mode, engine, port, base, head, selectQueries(args));
        }

        private static List<Query> selectQueries(String[] args) {
            List<Query> selected = new ArrayList<>();
            Set<Query> unique = new HashSet<>();
            for (int index = 4; index < args.length; index++) {
                String hash = args[index];
                Query query = Arrays.stream(Query.values())
                        .filter(candidate -> !candidate.invocations.isEmpty() && candidate.queryHash.equals(hash))
                        .findFirst().orElseThrow(IllegalArgumentException::new);
                if (!unique.add(query)) throw new IllegalArgumentException();
                selected.add(query);
            }
            return List.copyOf(selected);
        }
    }

    private static final class CheckProof {
        private final MessageDigest digest = digest();
        private int assertions;

        private CheckProof(Query query) {
            record("udak-schema-regression-query-proof-v1");
            record(query.queryHash);
            record(query.testHash);
            record(query.sql);
        }

        private void check(boolean valid) throws FixtureFailure {
            require(valid);
            assertions++;
        }

        private void record(Object value) {
            byte[] bytes = value == null ? new byte[0] : value.toString().getBytes(StandardCharsets.UTF_8);
            digest.update(ByteBuffer.allocate(Integer.BYTES).putInt(value == null ? -1 : bytes.length).array());
            digest.update(bytes);
        }

        private String finish() {
            record(assertions);
            return HexFormat.of().formatHex(digest.digest());
        }
    }

    private record Identity(String serverVersion, String driverVersion, String serverReleaseHash, String driverReleaseHash) {}

    private record Column(String name, String type, int width, boolean nullable) {
        private String json() {
            return "{\"table\":\"udak_entry\",\"column\":\"" + name + "\",\"type\":\"" + type + "\",\"width\":"
                    + width + ",\"nullable\":" + nullable + "}";
        }
    }

    private record Row(int id, String label) {}

    private record Invocation(Integer id, List<Row> expected) {}

    private static final class FixtureFailure extends Exception {}
}
