package dev.udak.rewrite.jdbc;

import dev.udak.rewrite.Rewrite;
import dev.udak.rewrite.Rewrite.Approval;
import dev.udak.rewrite.Rewrite.Check;
import dev.udak.rewrite.Rewrite.Code;
import dev.udak.rewrite.Rewrite.Denied;
import dev.udak.rewrite.Rewrite.Dialect;
import dev.udak.rewrite.Rewrite.Environment;
import dev.udak.rewrite.Rewrite.Evidence;
import dev.udak.rewrite.Rewrite.Plan;
import dev.udak.rewrite.Rewrite.Provider;
import dev.udak.rewrite.Rewrite.Registry;
import dev.udak.rewrite.Rewrite.Role;
import dev.udak.rewrite.Rewrite.Template;
import dev.udak.rewrite.jdbc.SelectiveJdbcClient.Parameters;
import dev.udak.rewrite.jdbc.SelectiveJdbcClient.SafeJdbcException;
import java.lang.reflect.InvocationHandler;
import java.lang.reflect.Proxy;
import java.sql.Connection;
import java.sql.DatabaseMetaData;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.ResultSetMetaData;
import java.sql.SQLException;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Set;
import org.springframework.jdbc.datasource.AbstractDataSource;
import org.springframework.jdbc.datasource.ConnectionHolder;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.transaction.support.TransactionSynchronizationManager;
import org.springframework.transaction.support.TransactionTemplate;

public final class SelectiveJdbcContractTest {
    private static final String FROM = " FROM udak_p5_entry WHERE status = ? ORDER BY id ASC ";
    private static final String SOURCE = "SELECT id, name" + FROM + "LIMIT ? OFFSET ?";
    private static final String TARGET = "SELECT id AS [id], name AS [name]" + FROM + "OFFSET ? ROWS FETCH NEXT ? ROWS ONLY";
    private static final String SERVER_RELEASE = "16.0.4322.1";
    private static final String DRIVER_RELEASE = "12.10.0.0";
    private static final String MARKER = "synthetic-jdbc-sentinel";
    private static final Instant NOW = Instant.parse("2026-11-18T00:00:00Z");
    private static final Instant EXPIRES = NOW.plusSeconds(60);
    private static final Environment ENV = environment("schema-1");
    private static final Template TEMPLATE = new Template("select-test-page", SOURCE, ENV);
    private static final Plan PLAN = new Plan(TARGET, List.of(Role.FILTER, Role.OFFSET, Role.LIMIT),
            List.of("id", "name"));
    private static final Provider PROVIDER = provider(PLAN);
    private static final Parameters PARAMETERS = new Parameters(MARKER, 4, 2);

    private int checks;

    public static void main(String[] args) {
        SelectiveJdbcContractTest test = new SelectiveJdbcContractTest();
        test.approvedExecution();
        test.approvalGate();
        test.metadataGate();
        test.failureRedaction();
        test.springConnectionOwnership();
        System.out.println("Selective JDBC contract checks: " + test.checks);
    }

    private void approvedExecution() {
        Probe probe = new Probe();
        SelectiveJdbcClient client = client(probe, approved(NOW), PROVIDER);
        List<Row> rows = client.query(TEMPLATE, PARAMETERS, (result, index) -> {
            check(result.getMetaData().getColumnLabel(1).equals("id"));
            return new Row(result.getInt(1), result.getString(2), index);
        });
        check(rows.equals(List.of(new Row(7, "sample", 0), new Row(9, null, 1))));
        check(probe.binds.equals(List.of(new Bind("setString", 1, MARKER), new Bind("setInt", 2, 2),
                new Bind("setInt", 3, 4))));
        check(probe.sql.equals(List.of(TARGET)));
        check(probe.connections == 1 && probe.closed == 1);
        check(probe.executions == 1 && probe.statementsClosed == 1 && probe.resultsClosed == 1);
        check(probe.timeout == 5 && probe.maxRows == 1_001);
        check(probe.autoCommit && probe.commits == 0 && probe.rollbacks == 0);
        check(PARAMETERS.toString().equals("Parameters[redacted]"));

        probe.binds.clear();
        client.query(TEMPLATE, new Parameters(null, 1_000, 1_000_000), (row, index) -> row.getInt(1));
        check(probe.binds.equals(List.of(new Bind("setString", 1, null), new Bind("setInt", 2, 1_000_000),
                new Bind("setInt", 3, 1_000))));
        invalidParameters(() -> new Parameters("x".repeat(1_025), 1, 0));
        invalidParameters(() -> new Parameters(null, 0, 0));
        invalidParameters(() -> new Parameters(null, 1_001, 0));
        invalidParameters(() -> new Parameters(null, 1, -1));
        invalidParameters(() -> new Parameters(null, 1, 1_000_001));
    }

    private void approvalGate() {
        Probe probe = new Probe();
        Registry active = approved(NOW);
        SelectiveJdbcClient client = client(probe, active, PROVIDER);
        denied(Code.MISSING_APPROVAL, () -> query(client(probe, registry(null, null, NOW), PROVIDER), TEMPLATE));
        denied(Code.MISSING_APPROVAL, () -> query(client, new Template("unregistered", SOURCE, ENV)));
        denied(Code.MISMATCH, () -> query(client, new Template(TEMPLATE.queryId(), SOURCE + " ", ENV)));
        denied(Code.MISMATCH, () -> query(client, new Template(TEMPLATE.queryId(), SOURCE,
                environment("schema-2"))));
        denied(Code.EXPIRED, () -> query(client(probe, approved(EXPIRES), PROVIDER), TEMPLATE));
        denied(Code.EVIDENCE_INVALID,
                () -> query(client(probe, registry(approval(), null, NOW), PROVIDER), TEMPLATE));
        Plan rebound = new Plan(TARGET, List.of(Role.FILTER, Role.LIMIT, Role.OFFSET), PLAN.columns());
        denied(Code.PLAN_MISMATCH, () -> query(client(probe, active, provider(rebound)), TEMPLATE));
        active.revoke(TEMPLATE.queryId());
        denied(Code.REVOKED, () -> query(client, TEMPLATE));
        check(probe.connections == 0 && probe.sql.isEmpty() && probe.executions == 0);
    }

    private void metadataGate() {
        Probe probe = new Probe();
        SelectiveJdbcClient client = client(probe, approved(NOW), PROVIDER);
        query(client, TEMPLATE);
        probe.sql.clear();
        probe.product = "PostgreSQL";
        denied(Code.MISMATCH, () -> query(client, TEMPLATE));
        probe.product = "Microsoft SQL Server";
        probe.serverRelease = "16.0.4322.2";
        denied(Code.MISMATCH, () -> query(client, TEMPLATE));
        probe.serverRelease = SERVER_RELEASE;
        probe.driverRelease = "12.10.1.0";
        denied(Code.MISMATCH, () -> query(client, TEMPLATE));
        check(probe.connections == 4 && probe.closed == 4);
        check(probe.sql.isEmpty() && probe.executions == 1);
    }

    private void failureRedaction() {
        Probe probe = new Probe();
        SelectiveJdbcClient client = client(probe, approved(NOW), PROVIDER);
        for (String failure : List.of("prepareStatement", "executeQuery", "close")) {
            probe.failure = failure;
            safeFailure(() -> query(client, TEMPLATE));
        }
        probe.failure = "";
        safeFailure(() -> client.query(TEMPLATE, PARAMETERS, (rows, index) -> {
            throw new SQLException(MARKER);
        }));
        safeFailure(() -> client.query(TEMPLATE, PARAMETERS, (rows, index) -> {
            throw new IllegalStateException(MARKER);
        }));
        safeFailure(() -> client.query(TEMPLATE, PARAMETERS, (rows, index) -> {
            AssertionError failure = new AssertionError(MARKER, new IllegalStateException(MARKER));
            failure.addSuppressed(new IllegalStateException(MARKER));
            throw failure;
        }));
        safeFailure(() -> client.query(TEMPLATE, PARAMETERS, (rows, index) -> null));
        safeFailure(() -> client.query(TEMPLATE, new Parameters(null, 1, 0), (rows, index) -> rows.getInt(1)));
        probe.firstLabel = "ID";
        int[] mapped = {0};
        safeFailure(() -> client.query(TEMPLATE, PARAMETERS, (rows, index) -> ++mapped[0]));
        check(mapped[0] == 0);
        check(probe.sql.size() == 9 && probe.sql.stream().allMatch(TARGET::equals));
        check(probe.connections == 9 && probe.closed == 9);
        check(probe.statementsClosed == 8 && probe.resultsClosed == 7);

        probe.firstLabel = "id";
        for (Error fatal : List.of(new InternalError(MARKER), new ThreadDeath())) {
            try {
                client.query(TEMPLATE, PARAMETERS, (rows, index) -> { throw fatal; });
                throw new AssertionError("Expected fatal error");
            } catch (VirtualMachineError | ThreadDeath failure) {
                check(failure == fatal);
            }
        }
        check(probe.connections == 11 && probe.closed == 11);
    }

    private void springConnectionOwnership() {
        Probe probe = new Probe();
        SelectiveJdbcClient client = client(probe, approved(NOW), PROVIDER);
        TransactionTemplate transaction = new TransactionTemplate(new DataSourceTransactionManager(probe));
        transaction.setTimeout(3);
        transaction.executeWithoutResult(status -> {
            ConnectionHolder holder = (ConnectionHolder) TransactionSynchronizationManager.getResource(probe);
            check(holder != null && holder.getConnection() == probe.lastConnection);
            client.query(TEMPLATE, PARAMETERS, (rows, index) -> {
                check(rows.getStatement().getConnection() == holder.getConnection());
                check(probe.connections == 1 && probe.closed == 0 && !probe.autoCommit);
                return rows.getInt(1);
            });
            check(probe.commits == 0 && probe.rollbacks == 0);
            check(!status.isRollbackOnly());
            check(probe.timeout > 0 && probe.timeout <= 3);
            status.setRollbackOnly();
        });
        check(probe.connections == 1 && probe.closed == 1 && probe.rollbacks == 1 && probe.commits == 0);
        check(probe.autoCommit && !TransactionSynchronizationManager.hasResource(probe));
        transaction.setTimeout(10);
        transaction.executeWithoutResult(status -> query(client, TEMPLATE));
        check(probe.timeout == 5);
        check(probe.connections == 2 && probe.closed == 2 && probe.rollbacks == 1 && probe.commits == 1);
    }

    private void safeFailure(Runnable call) {
        try {
            call.run();
            throw new AssertionError("Expected safe JDBC failure");
        } catch (SafeJdbcException failure) {
            check(failure.getMessage().equals("Approved JDBC query failed"));
            check(failure.getCause() == null && failure.getSuppressed().length == 0);
        }
    }

    private void denied(Code code, Runnable call) {
        try {
            call.run();
            throw new AssertionError("Expected policy denial");
        } catch (Denied denial) {
            check(denial.code() == code && denial.getCause() == null);
        }
    }

    private void invalidParameters(Runnable call) {
        try {
            call.run();
            throw new AssertionError("Expected invalid parameters");
        } catch (IllegalArgumentException failure) {
            check(failure.getMessage().equals("Invalid SELECT parameters"));
        }
    }

    private void check(boolean condition) {
        checks++;
        if (!condition) throw new AssertionError("Selective JDBC check failed at " + checks);
    }

    private static void query(SelectiveJdbcClient client, Template template) {
        client.query(template, PARAMETERS, (row, index) -> row.getInt(1));
    }

    private static SelectiveJdbcClient client(Probe probe, Registry registry, Provider provider) {
        return new SelectiveJdbcClient(probe, ENV, registry, provider);
    }

    private static Environment environment(String schema) {
        return new Environment(Dialect.POSTGRESQL, Dialect.SQLSERVER, Rewrite.fingerprint("17.12 fixture"),
                Rewrite.fingerprint(SERVER_RELEASE), Rewrite.fingerprint(DRIVER_RELEASE), schema,
                "test-provider-1", "test-runtime-1");
    }

    private static Provider provider(Plan plan) {
        return new Provider() {
            @Override public String version() { return ENV.providerVersion(); }
            @Override public Plan translate(Template template) { return plan; }
        };
    }

    private static Approval approval() {
        return new Approval(TEMPLATE.queryId(), Rewrite.fingerprint(SOURCE), ENV, Rewrite.fingerprint(TARGET),
                Rewrite.planFingerprint(PLAN), "test-evidence", "1".repeat(64), EXPIRES);
    }

    private static Registry approved(Instant now) {
        Approval approval = approval();
        Evidence proof = new Evidence(approval.evidenceId(), approval.evidenceDigest(), TEMPLATE.queryId(),
                approval.sourceFingerprint(), ENV, approval.targetFingerprint(), approval.planFingerprint(),
                NOW, EXPIRES, Set.of(Check.values()));
        return registry(approval, proof, now);
    }

    private static Registry registry(Approval approval, Evidence proof, Instant now) {
        return new Registry(approval == null ? Map.of() : Map.of(approval.queryId(), approval),
                proof == null ? Map.of() : Map.of(proof.id(), proof), Clock.fixed(now, ZoneOffset.UTC));
    }

    private record Row(int id, String name, int index) {}
    private record Bind(String setter, int index, Object value) {}

    private static final class Probe extends AbstractDataSource {
        int connections, closed, executions, statementsClosed, resultsClosed, commits, rollbacks, timeout, maxRows;
        String serverRelease = SERVER_RELEASE;
        String driverRelease = DRIVER_RELEASE;
        boolean autoCommit = true;
        String product = "Microsoft SQL Server";
        String firstLabel = "id";
        String failure = "";
        Connection lastConnection;
        final List<String> sql = new ArrayList<>();
        final List<Bind> binds = new ArrayList<>();

        @Override public Connection getConnection() {
            connections++;
            lastConnection = proxy(Connection.class, (self, method, args) -> switch (method.getName()) {
                case "getMetaData" -> metadata();
                case "prepareStatement" -> {
                    sql.add((String) args[0]);
                    failIf("prepareStatement");
                    yield statement((Connection) self);
                }
                case "getAutoCommit" -> autoCommit;
                case "setAutoCommit" -> { autoCommit = (Boolean) args[0]; yield null; }
                case "commit" -> { commits++; yield null; }
                case "rollback" -> { rollbacks++; yield null; }
                case "close" -> { closed++; failIf("close"); yield null; }
                default -> unexpected(method.getName());
            });
            return lastConnection;
        }

        @Override public Connection getConnection(String username, String password) throws SQLException {
            throw new SQLException("Unexpected credential overload");
        }

        private DatabaseMetaData metadata() {
            return proxy(DatabaseMetaData.class, (self, method, args) -> switch (method.getName()) {
                case "getDatabaseProductName" -> product;
                case "getDatabaseProductVersion" -> serverRelease;
                case "getDriverVersion" -> driverRelease;
                default -> unexpected(method.getName());
            });
        }

        private PreparedStatement statement(Connection connection) {
            return proxy(PreparedStatement.class, (self, method, args) -> switch (method.getName()) {
                case "getConnection" -> connection;
                case "setString", "setInt" -> { binds.add(new Bind(method.getName(), (Integer) args[0], args[1])); yield null; }
                case "setQueryTimeout" -> { timeout = (Integer) args[0]; yield null; }
                case "getQueryTimeout" -> timeout;
                case "setMaxRows" -> { maxRows = (Integer) args[0]; yield null; }
                case "executeQuery" -> { executions++; failIf("executeQuery"); yield results((PreparedStatement) self); }
                case "close" -> { statementsClosed++; yield null; }
                default -> unexpected(method.getName());
            });
        }

        private ResultSet results(PreparedStatement statement) {
            int[] row = {0};
            return proxy(ResultSet.class, (self, method, args) -> switch (method.getName()) {
                case "getStatement" -> statement;
                case "getMetaData" -> proxy(ResultSetMetaData.class, (m, field, index) -> switch (field.getName()) {
                    case "getColumnCount" -> 2;
                    case "getColumnLabel" -> ((Integer) index[0] == 1) ? firstLabel : "name";
                    default -> unexpected(field.getName());
                });
                case "next" -> ++row[0] <= 2;
                case "getInt" -> row[0] == 1 ? 7 : 9;
                case "getString" -> row[0] == 1 ? "sample" : null;
                case "close" -> { resultsClosed++; yield null; }
                default -> unexpected(method.getName());
            });
        }

        private void failIf(String phase) throws SQLException {
            if (phase.equals(failure)) throw new SQLException(MARKER);
        }
    }

    private static <T> T proxy(Class<T> type, InvocationHandler handler) {
        return type.cast(Proxy.newProxyInstance(type.getClassLoader(), new Class<?>[]{type}, (self, method, args) ->
                switch (method.getName()) {
                    case "equals" -> self == args[0];
                    case "hashCode" -> System.identityHashCode(self);
                    case "toString" -> "JDBC contract probe";
                    default -> handler.invoke(self, method, args);
                }));
    }

    private static Object unexpected(String method) {
        throw new AssertionError("Unexpected JDBC operation " + method);
    }
}
