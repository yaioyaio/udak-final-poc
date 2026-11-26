package dev.udak.pilot;

import dev.udak.inventory.InventoryCapture;
import dev.udak.observe.ObservationSink;
import dev.udak.observe.SqlObservation;
import dev.udak.observe.SqlObserver;
import dev.udak.observe.UnavailableReason;
import dev.udak.observe.jdbc.ObserveDataSource;
import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.Connection;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.UUID;
import javax.sql.DataSource;
import org.h2.jdbcx.JdbcDataSource;
import org.postgresql.ds.PGSimpleDataSource;

/** Replays the same COUNT cases with plain JDBC or UDAK Observe. */
public final class PairedDeviceCount {
    private static final String BASE = "fd9dc186e4134d4de9a129a91a7c4b1461781cde";
    private static final String HEAD = "924c9cf5d038084fda404185c8e7a60b3cd508f6";
    private static final String PROFILE = "8cb56304849d88c66145d48c1c689a11da10a40f5bbb45b5f07ac7ddb6b4d821";
    private static final String QUERY = "thingsboard-device-profile-count";
    private static final String TEST = "thingsboard-14858-count-replay";

    private static final class ReplaySink implements ObservationSink {
        private InventoryCapture active;

        @Override
        public void accept(SqlObservation observation) {
            if (active != null) active.accept(observation);
        }

        @Override
        public void accept(SqlObservation observation, UnavailableReason reason) {
            if (active != null) active.accept(observation, reason);
        }
    }

    private PairedDeviceCount() {}

    private static String requiredLine(BufferedReader input) throws IOException {
        String line = input.readLine();
        if (line == null || line.isBlank()) throw new IllegalArgumentException();
        return line;
    }

    private static void seed(Connection connection, UUID first, UUID second) throws SQLException {
        try (var create = connection.createStatement()) {
            create.execute("CREATE TEMP TABLE device (id uuid NOT NULL, tenant_id uuid NOT NULL)");
        }
        try (var insert = connection.prepareStatement("INSERT INTO device (id, tenant_id) VALUES (?, ?)")) {
            int row = 0;
            for (UUID tenant : new UUID[]{first, first, second}) {
                insert.setObject(1, new UUID(0, ++row));
                insert.setObject(2, tenant);
                if (insert.executeUpdate() != 1) throw new IllegalStateException();
            }
        }
    }

    private static void requireCount(ResultSet results, int expected) throws SQLException {
        if (!results.next() || results.getInt(1) != expected || results.next()) {
            throw new IllegalStateException();
        }
    }

    private static void verify(Connection connection, String sql, UUID tenant, int expected) throws SQLException {
        if (tenant == null) {
            try (var statement = connection.createStatement(); var results = statement.executeQuery(sql)) {
                requireCount(results, expected);
            }
            return;
        }
        try (var statement = connection.prepareStatement(sql)) {
            statement.setObject(1, tenant);
            try (var results = statement.executeQuery()) {
                requireCount(results, expected);
            }
        }
    }

    private static void replayCase(Connection connection, ReplaySink sink, String sql, UUID tenant,
            int expected, Path output, String revision) throws IOException, SQLException {
        if (sink == null) {
            verify(connection, sql, tenant, expected);
            return;
        }
        var capture = new InventoryCapture();
        sink.active = capture;
        try (var scope = capture.scope(QUERY, TEST)) {
            verify(connection, sql, tenant, expected);
        } finally {
            sink.active = null;
        }
        Files.writeString(output, capture.snapshotJsonWithObservedTests(revision, PROFILE));
    }

    private static void run(String[] args) throws IOException, SQLException {
        if (args.length != 3) throw new IllegalArgumentException();
        Path workspace = Path.of(args[0]);
        boolean observe = switch (args[2]) {
            case "plain" -> false;
            case "observe" -> true;
            default -> throw new IllegalArgumentException();
        };
        var input = new BufferedReader(new InputStreamReader(System.in, StandardCharsets.UTF_8));
        DataSource database = args[1].equals("h2") ? embedded() : postgres(args[1], requiredLine(input));

        UUID first = UUID.fromString(requiredLine(input));
        UUID second = UUID.fromString(requiredLine(input));
        String baseSql = requiredLine(input);
        String headSql = requiredLine(input);
        if (first.equals(second) || headSql.indexOf('?') == -1 || headSql.indexOf('?') != headSql.lastIndexOf('?')) {
            throw new IllegalArgumentException();
        }

        var sink = observe ? new ReplaySink() : null;
        var source = observe ? new ObserveDataSource(database, new SqlObserver(sink)) : database;
        try (var connection = source.getConnection()) {
            seed(connection, first, second);
            replayCase(connection, sink, baseSql, null, 3, workspace.resolve("BASE.json"), BASE);
            replayCase(connection, sink, headSql, first, 2, workspace.resolve("HEAD.json"), HEAD);
            replayCase(connection, sink, headSql, second, 1, workspace.resolve("CONTROL.json"), HEAD);
        }
    }

    private static DataSource embedded() {
        var h2 = new JdbcDataSource();
        h2.setURL("jdbc:h2:mem:paired-device-count;MODE=PostgreSQL");
        return h2;
    }

    private static DataSource postgres(String portArgument, String password) {
        int port = Integer.parseInt(portArgument);
        if (port < 1 || port > 65535) throw new IllegalArgumentException();
        var source = new PGSimpleDataSource();
        source.setServerNames(new String[]{"127.0.0.1"});
        source.setPortNumbers(new int[]{port});
        source.setDatabaseName("postgres");
        source.setUser("postgres");
        source.setPassword(password);
        source.setConnectTimeout(4);
        source.setSocketTimeout(5);
        return source;
    }

    public static void main(String[] args) {
        try {
            run(args);
            System.out.println("PAIRED_DEVICE_COUNT PASS");
        } catch (IllegalArgumentException invalid) {
            fail("INPUT");
        } catch (SQLException failure) {
            fail("JDBC");
        } catch (IOException failure) {
            fail("IO");
        } catch (RuntimeException failure) {
            fail("ASSERTION_OR_OBSERVE");
        }
    }

    private static void fail(String category) {
        System.err.println("PAIRED_DEVICE_COUNT FAIL " + category);
        System.exit(1);
    }
}
