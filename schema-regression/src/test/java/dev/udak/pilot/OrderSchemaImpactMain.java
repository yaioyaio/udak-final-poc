package dev.udak.pilot;

import dev.udak.inventory.InventoryCapture;
import dev.udak.observe.ObservationSink;
import dev.udak.observe.SqlObservation;
import dev.udak.observe.SqlObserver;
import dev.udak.observe.UnavailableReason;
import dev.udak.observe.hibernate.HibernateObserveInspector;
import dev.udak.observe.jdbc.ObserveDataSource;
import dev.udak.observe.mybatis.MyBatisObserveInterceptor;
import dev.udak.schema.SchemaSnapshotCollector;
import java.io.OutputStream;
import java.io.PrintStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.security.MessageDigest;
import java.util.HexFormat;
import java.util.Map;
import java.util.regex.Pattern;
import javax.sql.DataSource;
import org.springframework.jdbc.core.JdbcTemplate;

/** Exercises the legacy order application against isolated changes to its embedded H2 fixture. */
public final class OrderSchemaImpactMain {
    private static final String SCHEMA_FILE = "SCHEMA-SNAPSHOT.json";
    private static final String INVENTORY_FILE = "SQL-INVENTORY.json";
    private static final Map<String, String> TABLES = Map.of(
            "order_audit", "ORDER_AUDIT", "order_stock", "ORDER_STOCK", "placed_order", "PLACED_ORDER");
    private static final Pattern SCOPE = Pattern.compile("\"scope\":\"([a-f0-9]{64})\"");
    private final OrderFixture.Checks checks = new OrderFixture.Checks();

    public static void main(String[] args) {
        PrintStream output = System.out;
        PrintStream errors = System.err;
        String protocol = "ORDER_SCHEMA";
        var fixture = new OrderSchemaImpactMain();
        try (var discard = new PrintStream(OutputStream.nullOutputStream())) {
            System.setOut(discard);
            System.setErr(discard);
            if (args.length == 2 && "capture".equals(args[0])) {
                protocol = "ORDER_SCHEMA_CAPTURE";
                fixture.capture(Path.of(args[1]));
            } else if (args.length == 2 && "replay-related".equals(args[0]) && args[1].matches("[a-f0-9]{128}")) {
                protocol = "ORDER_SCHEMA_REPLAY";
                fixture.replayRelated(args[1]);
            } else {
                throw new IllegalArgumentException();
            }
        } catch (Exception | AssertionError | LinkageError failure) {
            output.println(protocol + " FAIL");
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
        output.println(protocol + " PASS");
        output.println("ASSERTIONS=" + fixture.checks.count());
    }

    private void capture(Path root) throws Exception {
        DataSource baseline = dataSource(Variant.BASE);
        String schema = collect(baseline, Variant.BASE);
        String baselineScope = scope(schema);
        save(root.resolve(Variant.BASE.directory).resolve(SCHEMA_FILE), schema);
        captureHead(root, Variant.RELATED, baselineScope);
        captureHead(root, Variant.CONTROL, baselineScope);
    }

    private void captureHead(Path root, Variant variant, String baselineScope) throws Exception {
        DataSource raw = dataSource(variant);
        String schema = collect(raw, variant);
        checks.equal(baselineScope, scope(schema), "SCHEMA_SCOPE");
        var capture = new ScopedCapture();
        var observer = new SqlObserver(capture);
        var observed = new ObserveDataSource(raw, observer);
        try (var app = OrderApplication.open(observed, new HibernateObserveInspector(observer),
                new MyBatisObserveInterceptor(observer))) {
            var request = OrderFixture.standardRequest();
            try (var order = capture.inventory.scope("order.place", "case.order.place")) {
                capture.active = true;
                verifyCommit(raw, app, request, () -> {});
            } finally {
                capture.active = false;
            }
            try (var auditCount = capture.inventory.scope("order.audit-count", "case.order.audit-count")) {
                capture.active = true;
                checks.equal(1L, jdbc(observed).queryForObject("SELECT COUNT(order_id) FROM order_audit", Long.class),
                        "AUDIT_COUNT");
            } finally {
                capture.active = false;
            }
        }
        Path directory = root.resolve(variant.directory);
        save(directory.resolve(SCHEMA_FILE), schema);
        save(directory.resolve(INVENTORY_FILE), capture.inventory.snapshotJson(variant.revision, baselineScope));
    }

    private void replayRelated(String expectedSchemaHash) throws Exception {
        DataSource committed = dataSource(Variant.RELATED);
        verifyReplaySchema(committed, expectedSchemaHash);
        var request = OrderFixture.standardRequest();
        try (var app = OrderApplication.open(committed, null, null)) {
            verifyCommit(committed, app, request, () -> OrderFixture.assertWritesInTransaction(checks, app, request));
        }

        DataSource rolledBack = dataSource(Variant.RELATED);
        verifyReplaySchema(rolledBack, expectedSchemaHash);
        var before = OrderFixture.snapshot(rolledBack);
        OrderFixture.assertInitial(checks, before);
        try (var app = OrderApplication.open(rolledBack, null, null)) {
            var injected = new InjectedFailure();
            try {
                app.orders().place(request, false, () -> {
                    OrderFixture.assertWritesInTransaction(checks, app, request);
                    throw injected;
                });
                throw new AssertionError("EXPECTED_ROLLBACK");
            } catch (InjectedFailure failure) {
                checks.require(failure == injected, "ROLLBACK_FAILURE_IDENTITY");
            }
            checks.equal(before, OrderFixture.snapshot(rolledBack), "ROLLBACK_ORDERS_STOCK_AUDIT");
        }
    }

    private void verifyReplaySchema(DataSource source, String expectedHash) throws Exception {
        byte[] metadata = collect(source, Variant.RELATED).getBytes(StandardCharsets.UTF_8);
        checks.equal(expectedHash, HexFormat.of().formatHex(MessageDigest.getInstance("SHA-512").digest(metadata)),
                "REPLAY_SCHEMA");
    }

    private void verifyCommit(DataSource raw, OrderApplication app, OrderService.Request request, Runnable afterWrites) {
        OrderFixture.assertInitial(checks, OrderFixture.snapshot(raw));
        var receipt = app.orders().place(request, false, afterWrites);
        OrderFixture.assertReceipt(checks, request, receipt);
        OrderFixture.assertCommitted(checks, OrderFixture.snapshot(raw), request);
    }

    private static DataSource dataSource(Variant variant) {
        DataSource source = OrderFixture.createDataSource();
        var jdbc = jdbc(source);
        jdbc.execute("ALTER TABLE order_audit ADD COLUMN fixture_note VARCHAR(16)");
        switch (variant) {
            case BASE -> { }
            case RELATED -> jdbc.execute("ALTER TABLE order_audit ALTER COLUMN event_code SET DATA TYPE VARCHAR(32)");
            case CONTROL -> jdbc.execute("ALTER TABLE order_audit ALTER COLUMN fixture_note SET DATA TYPE VARCHAR(32)");
        }
        return source;
    }

    private static JdbcTemplate jdbc(DataSource source) {
        var jdbc = new JdbcTemplate(source);
        jdbc.setQueryTimeout(5);
        return jdbc;
    }

    private static String collect(DataSource source, Variant variant) throws Exception {
        try (var connection = source.getConnection()) {
            return SchemaSnapshotCollector.collect(connection, variant.revision, connection.getCatalog(),
                    connection.getSchema(), TABLES);
        }
    }

    private String scope(String snapshot) {
        var match = SCOPE.matcher(snapshot);
        checks.require(match.find(), "SCHEMA_SCOPE_PRESENT");
        return match.group(1);
    }

    private static void save(Path target, String contents) throws Exception {
        Files.writeString(target, contents, StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE);
    }

    private enum Variant {
        BASE("base", "1"), RELATED("related", "2"), CONTROL("control", "3");

        private final String directory;
        private final String revision;

        Variant(String directory, String revisionDigit) {
            this.directory = directory;
            this.revision = revisionDigit.repeat(40);
        }
    }

    private static final class ScopedCapture implements ObservationSink {
        private final InventoryCapture inventory = new InventoryCapture();
        private boolean active;

        @Override
        public void accept(SqlObservation observation) {
            if (active) inventory.accept(observation);
        }

        @Override
        public void accept(SqlObservation observation, UnavailableReason reason) {
            if (active) inventory.accept(observation, reason);
        }
    }

    private static final class InjectedFailure extends RuntimeException {}
}
