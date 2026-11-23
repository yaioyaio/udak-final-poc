package dev.udak.pilot;

import dev.udak.inventory.InventoryCapture;
import dev.udak.observe.SqlObserver;
import dev.udak.observe.mybatis.MyBatisObserveInterceptor;
import dev.udak.schema.SchemaSnapshotCollector;
import java.io.OutputStream;
import java.io.PrintStream;
import java.lang.reflect.InvocationTargetException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.security.MessageDigest;
import java.sql.Connection;
import java.util.ArrayList;
import java.util.HexFormat;
import java.util.List;
import java.util.Map;
import java.util.regex.Pattern;
import javax.sql.DataSource;
import org.apache.ibatis.executor.statement.StatementHandler;
import org.apache.ibatis.plugin.Interceptor;
import org.apache.ibatis.plugin.Intercepts;
import org.apache.ibatis.plugin.Invocation;
import org.apache.ibatis.plugin.Signature;
import org.springframework.jdbc.core.JdbcTemplate;

/** Captures each prepared stock UPDATE from the pinned order application on independent H2 fixtures. */
public final class OrderStockUpdateMain {
    private static final Map<String, String> TABLES = Map.of(
            "order_audit", "ORDER_AUDIT", "order_stock", "ORDER_STOCK", "placed_order", "PLACED_ORDER");
    private static final Pattern SCOPE = Pattern.compile("\"scope\":\"([a-f0-9]{64})\"");
    private final OrderFixture.Checks checks = new OrderFixture.Checks();

    public static void main(String[] args) {
        PrintStream output = System.out;
        PrintStream errors = System.err;
        String protocol = "ORDER_STOCK";
        var fixture = new OrderStockUpdateMain();
        try (var discard = new PrintStream(OutputStream.nullOutputStream())) {
            System.setOut(discard);
            System.setErr(discard);
            if (args.length == 2 && "capture".equals(args[0])) {
                protocol = "ORDER_STOCK_CAPTURE";
                fixture.capture(Path.of(args[1]), Capture.SEPARATE);
            } else if (args.length == 2 && "capture-fingerprints".equals(args[0])) {
                protocol = "ORDER_STOCK_FINGERPRINT_CAPTURE";
                fixture.capture(Path.of(args[1]), Capture.SHARED);
            } else if (args.length == 2 && "capture-observed-tests".equals(args[0])) {
                protocol = "ORDER_STOCK_OBSERVED_TESTS_CAPTURE";
                fixture.capture(Path.of(args[1]), Capture.OBSERVED_TESTS);
            } else if (args.length == 2 && "replay-related".equals(args[0]) && args[1].matches("[a-f0-9]{64}")) {
                protocol = "ORDER_STOCK_REPLAY";
                fixture.replayRelated(args[1], Mode.ON);
            } else if (args.length == 2 && "replay-related-off".equals(args[0]) && args[1].matches("[a-f0-9]{64}")) {
                protocol = "ORDER_STOCK_OFF_REPLAY";
                fixture.replayRelated(args[1], Mode.OFF);
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

    private void capture(Path root, Capture capture) throws Exception {
        String baselineScope = captureVariant(root, Variant.BASE, null, capture);
        captureVariant(root, Variant.RELATED, baselineScope, capture);
        captureVariant(root, Variant.CONTROL, baselineScope, capture);
    }

    private String captureVariant(Path root, Variant variant, String baselineScope, Capture capture) throws Exception {
        DataSource off = dataSource(variant);
        String schema = collect(off, variant);
        var match = SCOPE.matcher(schema);
        checks.require(match.find(), "SCHEMA_SCOPE_PRESENT");
        String scope = match.group(1);
        if (baselineScope != null) {
            checks.equal(baselineScope, scope, "SCHEMA_SCOPE");
        }

        var inventory = new InventoryCapture();
        Path directory = root.resolve(variant.directory);
        boolean sharedQueryId = capture != Capture.SEPARATE;
        String offSql = captureCommit(off, Mode.OFF, inventory, sharedQueryId);
        if (sharedQueryId && variant != Variant.BASE) {
            Files.createDirectories(directory);
            save(directory.resolve("STOCK-OFF-INVENTORY.json"), inventory.snapshotJson(variant.revision, scope));
        }
        String onSql = captureCommit(dataSource(variant), Mode.ON, inventory, sharedQueryId);
        Files.createDirectories(directory);
        save(directory.resolve("SCHEMA-SNAPSHOT.json"), schema);
        if (variant != Variant.BASE) {
            String snapshot = capture == Capture.OBSERVED_TESTS
                    ? inventory.snapshotJsonWithObservedTests(variant.revision, scope)
                    : inventory.snapshotJson(variant.revision, scope);
            save(directory.resolve("SQL-INVENTORY.json"), snapshot);
            save(directory.resolve("STOCK-OFF.sql"), offSql);
            save(directory.resolve("STOCK-ON.sql"), onSql);
        }
        return scope;
    }

    private String captureCommit(DataSource source, Mode mode, InventoryCapture inventory, boolean sharedQueryId)
            throws Exception {
        var capture = new PreparedSqlCapture(inventory);
        String queryId = sharedQueryId ? "order.stock" : mode.queryId;
        try (var app = OrderApplication.open(source, null, capture);
             var ignored = inventory.scope(queryId, mode.testId)) {
            verifyCommit(source, app, OrderFixture.standardRequest(), mode);
        }
        checks.equal(1, capture.prepared.size(), "STOCK_PREPARE_COUNT");
        return capture.prepared.get(0);
    }

    private void replayRelated(String expectedHash, Mode mode) throws Exception {
        var request = mode == Mode.ON ? OrderFixture.standardRequest() : OrderFixture.inactiveStockRequest();
        DataSource committed = replaySource(expectedHash);
        try (var app = OrderApplication.open(committed, null, null)) {
            verifyCommit(committed, app, request, mode);
        }

        DataSource rolledBack = replaySource(expectedHash);
        var before = OrderFixture.snapshot(rolledBack);
        OrderFixture.assertInitial(checks, before);
        try (var app = OrderApplication.open(rolledBack, null, null)) {
            var injected = new InjectedFailure();
            try {
                app.orders().place(request, mode.requireActive, () -> {
                    OrderFixture.assertWritesInTransaction(checks, app, request);
                    throw injected;
                });
                throw new AssertionError("EXPECTED_ROLLBACK");
            } catch (InjectedFailure failure) {
                checks.require(failure == injected, "ROLLBACK_FAILURE_IDENTITY");
            }
            checks.equal(before, OrderFixture.snapshot(rolledBack), "ROLLBACK_ORDERS_STOCK_AUDIT");

            if (mode == Mode.ON) {
                try {
                    app.orders().place(OrderFixture.inactiveStockRequest(), true,
                            () -> { throw new AssertionError("INACTIVE_STOCK_WRITTEN"); });
                    throw new AssertionError("EXPECTED_INACTIVE_GUARD");
                } catch (OrderService.StockUnavailable expected) {
                    checks.equal(before, OrderFixture.snapshot(rolledBack), "INACTIVE_ORDERS_STOCK_AUDIT");
                }
            }
        }
    }

    private DataSource replaySource(String expectedHash) throws Exception {
        DataSource source = dataSource(Variant.RELATED);
        byte[] schema = collect(source, Variant.RELATED).getBytes(StandardCharsets.UTF_8);
        checks.equal(expectedHash, HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(schema)),
                "REPLAY_SCHEMA");
        return source;
    }

    private void verifyCommit(DataSource source, OrderApplication app, OrderService.Request request, Mode mode) {
        OrderFixture.assertInitial(checks, OrderFixture.snapshot(source));
        var receipt = app.orders().place(request, mode.requireActive,
                () -> OrderFixture.assertWritesInTransaction(checks, app, request));
        OrderFixture.assertReceipt(checks, request, receipt);
        OrderFixture.assertCommitted(checks, OrderFixture.snapshot(source), request);
    }

    private static DataSource dataSource(Variant variant) {
        DataSource source = OrderFixture.createDataSource();
        var jdbc = new JdbcTemplate(source);
        jdbc.setQueryTimeout(5);
        jdbc.execute("ALTER TABLE order_stock ADD COLUMN fixture_note VARCHAR(16)");
        switch (variant) {
            case BASE -> { }
            case RELATED -> jdbc.execute("ALTER TABLE order_stock ALTER COLUMN active DROP NOT NULL");
            case CONTROL -> jdbc.execute("ALTER TABLE order_stock ALTER COLUMN fixture_note SET DATA TYPE VARCHAR(32)");
        }
        return source;
    }

    private static String collect(DataSource source, Variant variant) throws Exception {
        try (var connection = source.getConnection()) {
            return SchemaSnapshotCollector.collect(connection, variant.revision, connection.getCatalog(),
                    connection.getSchema(), TABLES);
        }
    }

    private static void save(Path target, String contents) throws Exception {
        Files.writeString(target, contents, StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE);
    }

    private enum Capture { SEPARATE, SHARED, OBSERVED_TESTS }

    private enum Mode {
        OFF(false, "order.stock-off", "case.order.stock-off"),
        ON(true, "order.stock-on", "case.order.stock-on");

        private final boolean requireActive;
        private final String queryId;
        private final String testId;

        Mode(boolean requireActive, String queryId, String testId) {
            this.requireActive = requireActive;
            this.queryId = queryId;
            this.testId = testId;
        }
    }

    private enum Variant {
        BASE("base", "4"), RELATED("related", "5"), CONTROL("control", "6");

        private final String directory;
        private final String revision;

        Variant(String directory, String revisionDigit) {
            this.directory = directory;
            this.revision = revisionDigit.repeat(40);
        }
    }

    @Intercepts(@Signature(type = StatementHandler.class, method = "prepare", args = {
        Connection.class, Integer.class
    }))
    private static final class PreparedSqlCapture implements Interceptor {
        private final MyBatisObserveInterceptor observe;
        private final List<String> prepared = new ArrayList<>();

        PreparedSqlCapture(InventoryCapture inventory) {
            observe = new MyBatisObserveInterceptor(new SqlObserver(inventory));
        }

        @Override
        public Object plugin(Object target) {
            // OrderApplication accepts one plugin. Preserve Observe's Executor and prepare interceptors.
            return Interceptor.super.plugin(observe.plugin(target));
        }

        @Override
        public Object intercept(Invocation invocation) throws Throwable {
            var handler = (StatementHandler) invocation.getTarget();
            try {
                Object statement = invocation.proceed();
                prepared.add(handler.getBoundSql().getSql());
                return statement;
            } catch (InvocationTargetException failure) {
                throw failure.getCause();
            }
        }
    }

    private static final class InjectedFailure extends RuntimeException {}
}
