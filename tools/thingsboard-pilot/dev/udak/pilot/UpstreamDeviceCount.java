package dev.udak.pilot;

import dev.udak.inventory.InventoryCapture;
import dev.udak.observe.ObservationSink;
import dev.udak.observe.SqlObservation;
import dev.udak.observe.SqlObserver;
import dev.udak.observe.UnavailableReason;
import dev.udak.observe.jdbc.ObserveDataSource;
import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.Connection;
import java.util.UUID;
import org.postgresql.ds.PGSimpleDataSource;

/** Runs the verified upstream COUNT statements against disposable PostgreSQL data. */
public final class UpstreamDeviceCount {
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

    private UpstreamDeviceCount() {}

    private static void capture(Connection connection, ReplaySink sink, String sql,
            int expected, Path output, String revision) throws Exception {
        var capture = new InventoryCapture();
        sink.active = capture;
        try (var scope = capture.scope(QUERY, TEST);
                var statement = connection.createStatement();
                var results = statement.executeQuery(sql)) {
            if (!results.next() || results.getInt(1) != expected || results.next()) {
                throw new IllegalStateException("Unexpected upstream device count");
            }
        } finally {
            sink.active = null;
        }
        Files.writeString(output, capture.snapshotJsonWithObservedTests(revision, PROFILE));
    }

    public static void main(String[] args) throws Exception {
        Path workspace = Path.of(args[0]);
        int port = Integer.parseInt(args[1]);
        var input = new BufferedReader(new InputStreamReader(System.in, StandardCharsets.UTF_8));
        String password = input.readLine();
        UUID firstTenant = UUID.fromString(input.readLine());
        UUID secondTenant = UUID.fromString(input.readLine());
        String baseSql = input.readLine();
        String headSql = input.readLine();
        String controlSql = input.readLine();
        var postgres = new PGSimpleDataSource();
        postgres.setServerNames(new String[]{"127.0.0.1"});
        postgres.setPortNumbers(new int[]{port});
        postgres.setDatabaseName("postgres");
        postgres.setUser("postgres");
        postgres.setPassword(password);
        postgres.setConnectTimeout(4);
        postgres.setSocketTimeout(5);
        var sink = new ReplaySink();
        var observed = new ObserveDataSource(postgres, new SqlObserver(sink));
        try (var connection = observed.getConnection()) {
            try (var create = connection.createStatement()) {
                create.execute("CREATE TEMP TABLE device (id uuid NOT NULL, tenant_id uuid NOT NULL)");
            }
            try (var insert = connection.prepareStatement("INSERT INTO device (id, tenant_id) VALUES (?, ?)")) {
                for (var tenant : new UUID[]{firstTenant, secondTenant}) {
                    insert.setObject(1, UUID.randomUUID());
                    insert.setObject(2, tenant);
                    if (insert.executeUpdate() != 1) throw new IllegalStateException("Fixture insert failed");
                }
            }
            capture(connection, sink, baseSql, 2, workspace.resolve("BASE.json"), BASE);
            capture(connection, sink, headSql, 1, workspace.resolve("HEAD.json"), HEAD);
            capture(connection, sink, controlSql, 1, workspace.resolve("CONTROL.json"), HEAD);
        }
    }
}
