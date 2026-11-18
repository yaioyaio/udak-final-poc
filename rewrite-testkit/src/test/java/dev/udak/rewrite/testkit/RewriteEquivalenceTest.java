package dev.udak.rewrite.testkit;

import static dev.udak.rewrite.testkit.RewriteFixture.QUERY_TIMEOUT_SECONDS;
import static dev.udak.rewrite.testkit.RewriteFixture.TABLE;

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
import dev.udak.rewrite.jdbc.SelectiveJdbcClient;
import dev.udak.rewrite.jdbc.SelectiveJdbcClient.Parameters;
import dev.udak.rewrite.jsqlparser.PaginationRewriteProvider;
import java.io.OutputStream;
import java.io.PrintStream;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.sql.Connection;
import java.sql.DatabaseMetaData;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.ResultSetMetaData;
import java.sql.SQLException;
import java.sql.Types;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.HexFormat;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.logging.Level;
import java.util.logging.LogManager;
import java.util.logging.Logger;
import java.util.regex.Pattern;
import javax.sql.DataSource;
import org.springframework.jdbc.datasource.ConnectionHolder;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.jdbc.datasource.DataSourceUtils;
import org.springframework.transaction.support.TransactionSynchronizationManager;
import org.springframework.transaction.support.TransactionTemplate;

/** Runs the closed fixture on one exclusive disposable database owned by the caller. */
public final class RewriteEquivalenceTest {
    public static final List<String> CHECKS = List.of("BASELINE", "PAGING", "NULL_MAPPING", "BIND_ORDER",
            "LABELS_TYPES", "TRANSACTION", "DEFAULT_DENY", "EVIDENCE");

    private static final List<String> COLUMNS = List.of("id", "name");
    private static final List<Role> SOURCE_ROLES = List.of(Role.FILTER, Role.LIMIT, Role.OFFSET);
    private static final List<Role> OFFSET_ROLES = List.of(Role.FILTER, Role.OFFSET, Role.LIMIT);
    private static final String BASELINE_SQL = "SELECT id, name FROM " + TABLE + " WHERE status = ? ORDER BY id ASC";
    private static final String SOURCE_SQL = BASELINE_SQL + " LIMIT ? OFFSET ?";
    private static final String EVIDENCE_ID = "p5-equivalence-test";
    private static final String LOCAL_SOURCE_RELEASE = Rewrite.fingerprint("p5-local-PostgreSQL-template-only");
    private static final Pattern RELEASE_HASH = Pattern.compile("[0-9a-f]{64}");
    private static final Instant VERIFIED_AT = Instant.parse("2026-11-18T00:00:00Z");
    private static final Instant VALID_UNTIL = VERIFIED_AT.plusSeconds(60);
    private static final List<Page> PAGES = List.of(
            new Page("middle", new Parameters("active", 2, 1), List.of(new Row(20, null), new Row(30, "charlie"))),
            new Page("first", new Parameters("active", 3, 0), List.of(new Row(10, "alpha"), new Row(20, null),
                    new Row(30, "charlie"))),
            new Page("last", new Parameters("active", 2, 4), List.of(new Row(50, "echo"))),
            new Page("past-end", new Parameters("active", 2, 5), List.of()),
            new Page("no-match", new Parameters("missing", 3, 1), List.of()),
            new Page("null-filter", new Parameters(null, 3, 1), List.of()),
            new Page("other-filter", new Parameters("other", 2, 1), List.of(new Row(35, "other-two"))));

    public record Summary(int checks, int assertions, String evidenceDigest, String resultDigest,
                          boolean sourceSqlExecuted) {}

    private final DataSource source;
    private final JdbcProbe probe;
    private final Provider provider = new PaginationRewriteProvider(Set.of(TABLE), Set.of("id", "name", "status"));
    private final Template template;
    private final Environment environment;
    private int assertions;

    private RewriteEquivalenceTest(DataSource source, Dialect target, String targetReleaseHash,
                                   String driverReleaseHash, String sourceReleaseHash) {
        this.source = source;
        probe = new JdbcProbe(source);
        environment = new Environment(Dialect.POSTGRESQL, target, sourceReleaseHash, targetReleaseHash,
                driverReleaseHash, "p5-schema-1", provider.version(), "p5-runtime-1");
        template = new Template("p5.select-entry-page", SOURCE_SQL, environment);
    }

    public static void main(String[] args) {
        PrintStream out = suppressRuntimeOutput();
        if (args.length != 0) {
            out.println("H2 NOT RUN: INVALID_ARGUMENT");
            System.exit(2);
            return;
        }
        try {
            DataSource local = LocalH2.dataSource();
            Summary summary;
            try (Connection owner = local.getConnection()) {
                DatabaseMetaData metadata = owner.getMetaData();
                summary = run(local, Dialect.H2, Rewrite.fingerprint(metadata.getDatabaseProductVersion()),
                        Rewrite.fingerprint(metadata.getDriverVersion()));
            }
            out.println("H2 PASS");
            out.println("CHECKS=" + summary.checks());
            out.println("CLEANUP=CONFIRMED");
            for (String check : CHECKS) out.println("SCENARIO=" + check + ":PASS");
            out.println("ASSERTIONS=" + summary.assertions());
            out.println("EVIDENCE_SHA256=" + summary.evidenceDigest());
            out.println("RESULT_SHA256=" + summary.resultDigest());
            out.println("SOURCE_SQL_EXECUTED=" + summary.sourceSqlExecuted());
        } catch (Throwable failure) {
            Failure report = failure instanceof Failure safe ? safe : new Failure("EXECUTION_ERROR", failure);
            out.println("H2 FAIL: " + report.code());
            for (String diagnostic : report.diagnostics()) out.println("DIAGNOSTIC=" + diagnostic);
            System.exit(1);
        }
    }

    /** Install process-lifetime output suppression before creating the runtime DataSource. */
    public static PrintStream suppressRuntimeOutput() {
        PrintStream out = System.out;
        PrintStream sink = new PrintStream(OutputStream.nullOutputStream());
        System.setOut(sink);
        System.setErr(sink);
        LogManager.getLogManager().reset();
        Logger.getLogger("").setLevel(Level.OFF);
        System.setProperty("org.jboss.logging.provider", "jdk");
        return out;
    }

    public static Summary run(DataSource source, Dialect target, String targetReleaseHash, String driverReleaseHash) {
        if (target != Dialect.H2) throw new Failure("SOURCE_RELEASE_REQUIRED");
        return run(source, target, targetReleaseHash, driverReleaseHash, LOCAL_SOURCE_RELEASE);
    }

    public static Summary run(DataSource source, Dialect target, String targetReleaseHash, String driverReleaseHash,
                              String sourceReleaseHash) {
        if (source == null || target == null || !validRelease(targetReleaseHash) || !validRelease(driverReleaseHash)
                || !validRelease(sourceReleaseHash) || (target == Dialect.POSTGRESQL
                && !targetReleaseHash.equals(sourceReleaseHash))) {
            throw new Failure("INVALID_PROFILE");
        }
        if (TransactionSynchronizationManager.isSynchronizationActive()) throw new Failure("CALLER_TRANSACTION_ACTIVE");
        return at("EXECUTION_ERROR", () -> new RewriteEquivalenceTest(source, target, targetReleaseHash,
                driverReleaseHash, sourceReleaseHash).verify());
    }

    private static boolean validRelease(String hash) {
        return hash != null && RELEASE_HASH.matcher(hash).matches();
    }

    private Summary verify() {
        try (RewriteFixture fixture = new RewriteFixture(source, environment)) {
            at("FIXTURE_BOOTSTRAP", () -> { fixture.create(); return null; });
            boolean sourceSqlExecuted = environment.target() == Dialect.POSTGRESQL;
            List<List<Row>> baseline = at("BASELINE", () -> baseline(sourceSqlExecuted));
            Plan plan = at("PROVIDER_PLAN", () -> provider.translate(template));
            at("BIND_ORDER", () -> {
                List<Role> order = switch (environment.target()) {
                    case H2, POSTGRESQL, MYSQL -> SOURCE_ROLES;
                    case SQLSERVER, ORACLE -> OFFSET_ROLES;
                };
                require(plan.bindOrder().equals(order));
                require(plan.columns().equals(COLUMNS));
                return null;
            });
            List<List<Row>> targets = at("PAGING", () -> probeTargets(plan, baseline));
            at("NULL_MAPPING", () -> {
                require(targets.get(0).get(0).name() == null);
                require(targets.get(5).isEmpty());
                return null;
            });
            at("TRANSACTION_PROBE", () -> {
                transaction(plan.sql(), parameters -> read(probe, plan.sql(), parameters, plan.bindOrder(), true), false);
                return null;
            });
            at("DEFAULT_DENY", () -> { verifyDefaultDeny(); return null; });

            String targetResultDigest = resultsDigest(targets);
            String evidenceDigest = evidenceDigest(plan, targetResultDigest, sourceSqlExecuted);
            Evidence evidence = createProof(plan, evidenceDigest);
            Approval approval = createApproval(evidence);
            Registry registry = registry(approval, evidence, VERIFIED_AT);
            SelectiveJdbcClient client = new SelectiveJdbcClient(probe, environment, registry, provider);
            List<List<Row>> actual = at("APPROVED_EXECUTION", () -> approvedTargets(client, plan, targets));
            at("TRANSACTION", () -> {
                transaction(plan.sql(), parameters -> selected(client, parameters), true);
                return null;
            });
            at("EVIDENCE", () -> {
                verifyEvidenceDenials(approval, evidence, registry, client);
                require(resultsDigest(actual).equals(targetResultDigest));
                return null;
            });
            return new Summary(CHECKS.size(), assertions, evidenceDigest, targetResultDigest, sourceSqlExecuted);
        }
    }

    private List<List<Row>> baseline(boolean sourceSqlExecuted) throws SQLException {
        List<List<Row>> pages = new ArrayList<>();
        for (Page page : PAGES) {
            try (Connection connection = source.getConnection()) {
                List<Row> full = read(connection, BASELINE_SQL, page.parameters(), List.of(Role.FILTER), false);
                int start = Math.min(page.parameters().offset(), full.size());
                int end = Math.min(start + page.parameters().limit(), full.size());
                List<Row> rows = List.copyOf(full.subList(start, end));
                require(rows.equals(page.expected()));
                if (sourceSqlExecuted) {
                    require(read(connection, SOURCE_SQL, page.parameters(), SOURCE_ROLES, false).equals(rows));
                }
                pages.add(rows);
            }
        }
        return pages;
    }

    private List<List<Row>> probeTargets(Plan plan, List<List<Row>> baseline) throws SQLException {
        List<List<Row>> pages = new ArrayList<>();
        try (Connection connection = probe.getConnection()) {
            for (Page page : PAGES) {
                int prepares = probe.prepares();
                List<Row> rows = read(connection, plan.sql(), page.parameters(), plan.bindOrder(), true);
                require(rows.equals(baseline.get(pages.size())));
                verifyPrepared(plan, page.parameters(), prepares);
                pages.add(rows);
            }
        }
        return pages;
    }

    private List<List<Row>> approvedTargets(SelectiveJdbcClient client, Plan plan, List<List<Row>> targets) {
        List<List<Row>> pages = new ArrayList<>();
        for (Page page : PAGES) {
            int prepares = probe.prepares();
            List<Row> rows = selected(client, page.parameters());
            require(rows.equals(targets.get(pages.size())));
            verifyPrepared(plan, page.parameters(), prepares);
            pages.add(rows);
        }
        return pages;
    }

    private void verifyPrepared(Plan plan, Parameters parameters, int prepares) {
        at("BIND_ORDER", () -> {
            require(probe.prepares() == prepares + 1 && plan.sql().equals(probe.sql()));
            boolean limitFirst = switch (environment.target()) {
                case H2, POSTGRESQL, MYSQL -> true;
                case SQLSERVER, ORACLE -> false;
            };
            require(probe.binds().equals(List.of(new JdbcProbe.Bind("setString", 1, parameters.filter()),
                    new JdbcProbe.Bind("setInt", 2, limitFirst ? parameters.limit() : parameters.offset()),
                    new JdbcProbe.Bind("setInt", 3, limitFirst ? parameters.offset() : parameters.limit()))));
            return null;
        });
    }

    private List<Row> selected(SelectiveJdbcClient client, Parameters parameters) {
        return client.query(template, parameters, (rows, index) -> {
            validateMetadata(rows.getMetaData(), true);
            int id = rows.getInt("id");
            require(!rows.wasNull());
            return new Row(id, rows.getString("name"));
        });
    }

    private List<Row> read(DataSource dataSource, String sql, Parameters parameters, List<Role> roles, boolean target)
            throws SQLException {
        Connection connection = DataSourceUtils.getConnection(dataSource);
        try {
            return read(connection, sql, parameters, roles, target);
        } finally {
            DataSourceUtils.doReleaseConnection(connection, dataSource);
        }
    }

    private List<Row> read(Connection connection, String sql, Parameters parameters, List<Role> roles, boolean target)
            throws SQLException {
        try (PreparedStatement statement = connection.prepareStatement(sql)) {
            statement.setQueryTimeout(QUERY_TIMEOUT_SECONDS);
            statement.setMaxRows(17);
            int index = 1;
            for (Role role : roles) {
                switch (role) {
                    case FILTER -> statement.setString(index, parameters.filter());
                    case LIMIT -> statement.setInt(index, parameters.limit());
                    case OFFSET -> statement.setInt(index, parameters.offset());
                }
                index++;
            }
            try (ResultSet result = statement.executeQuery()) {
                at("LABELS_TYPES", () -> { validateMetadata(result.getMetaData(), target); return null; });
                List<Row> rows = new ArrayList<>();
                while (result.next()) {
                    require(rows.size() < 16);
                    int id = result.getInt(1);
                    require(!result.wasNull());
                    rows.add(new Row(id, result.getString(2)));
                }
                return List.copyOf(rows);
            }
        }
    }

    private void validateMetadata(ResultSetMetaData metadata, boolean target) throws SQLException {
        require(metadata.getColumnCount() == 2);
        boolean uppercase = !target && (environment.target() == Dialect.H2 || environment.target() == Dialect.ORACLE);
        for (int i = 0; i < COLUMNS.size(); i++) {
            String label = uppercase ? COLUMNS.get(i).toUpperCase(Locale.ROOT) : COLUMNS.get(i);
            require(label.equals(metadata.getColumnLabel(i + 1)));
        }
        // Oracle exposes INTEGER (NUMBER(38,0)) under its native JDBC decimal type.
        int idType = metadata.getColumnType(1);
        if (environment.target() == Dialect.ORACLE) {
            require((idType == Types.NUMERIC || idType == Types.DECIMAL) && metadata.getScale(1) == 0);
        } else {
            require(idType == Types.INTEGER);
        }
        require(metadata.getColumnType(2) == Types.VARCHAR);
    }

    private void transaction(String sql, PagedQuery query, boolean approved) throws SQLException {
        TransactionTemplate tx = new TransactionTemplate(new DataSourceTransactionManager(probe));
        tx.setTimeout(10);
        int id = approved ? 72 : 71;
        String filter = approved ? "approved-tx" : "probe-tx";
        Parameters parameters = new Parameters(filter, 2, 0);
        List<Row> pending = List.of(new Row(id, "transaction-row"));
        for (boolean rollback : List.of(true, false)) {
            tx.executeWithoutResult(status -> at("TRANSACTION", () -> {
                ConnectionHolder holder = (ConnectionHolder) TransactionSynchronizationManager.getResource(probe);
                require(holder != null);
                Connection connection = holder.getConnection();
                int connections = probe.connections();
                int closed = probe.closed();
                require(!connection.getAutoCommit());
                require(RewriteFixture.insert(connection, id, "transaction-row", filter) == 1);
                require(query.query(parameters).equals(pending));
                require(probe.preparedOn() == connection && sql.equals(probe.sql()));
                require(probe.connections() == connections && probe.closed() == closed);
                require(!connection.getAutoCommit() && !status.isRollbackOnly());
                if (rollback) status.setRollbackOnly();
                return null;
            }));
            require(!TransactionSynchronizationManager.hasResource(probe));
            require(query.query(parameters).equals(rollback ? List.of() : pending));
        }
    }

    private void verifyDefaultDeny() {
        Registry empty = new Registry(Map.of(), Map.of(), clock(VERIFIED_AT));
        SelectiveJdbcClient client = new SelectiveJdbcClient(probe, environment, empty, provider);
        denied(Code.MISSING_APPROVAL, () -> selected(client, PAGES.get(0).parameters()));
        int prepares = probe.prepares();
        int connections = probe.connections();
        denied(Code.UNSUPPORTED, () -> provider.translate(new Template(template.queryId(), SOURCE_SQL + ";", environment)));
        require(probe.prepares() == prepares && probe.connections() == connections);
    }

    private void verifyEvidenceDenials(Approval approval, Evidence proof, Registry registry, SelectiveJdbcClient client) {
        Parameters parameters = PAGES.get(0).parameters();
        denied(Code.MISSING_APPROVAL, () -> query(client, new Template("unknown-query", SOURCE_SQL, environment), parameters));
        denied(Code.MISMATCH, () -> query(client, new Template(template.queryId(), SOURCE_SQL + " ", environment), parameters));

        Environment drifted = new Environment(environment.source(), environment.target(), environment.sourceVersion(),
                environment.targetVersion(), environment.driverVersion(), environment.schemaVersion(),
                environment.providerVersion(), "p5-runtime-other");
        denied(Code.MISMATCH, () -> query(client, new Template(template.queryId(), SOURCE_SQL, drifted), parameters));
        denied(Code.EXPIRED, () -> selected(new SelectiveJdbcClient(probe, environment,
                registry(approval, proof, VALID_UNTIL), provider), parameters));

        Evidence wrongDigest = new Evidence(proof.id(), Rewrite.fingerprint("tampered"), proof.queryId(),
                proof.sourceFingerprint(), proof.environment(), proof.targetFingerprint(), proof.planFingerprint(),
                proof.verifiedAt(), proof.validUntil(), proof.passed());
        Evidence wrongTarget = new Evidence(proof.id(), proof.digest(), proof.queryId(), proof.sourceFingerprint(),
                proof.environment(), Rewrite.fingerprint("different target"), proof.planFingerprint(), proof.verifiedAt(),
                proof.validUntil(), proof.passed());
        for (Evidence tampered : List.of(wrongDigest, wrongTarget)) {
            denied(Code.EVIDENCE_INVALID, () -> selected(new SelectiveJdbcClient(probe, environment,
                    registry(approval, tampered, VERIFIED_AT), provider), parameters));
        }
        registry.revoke(template.queryId());
        denied(Code.REVOKED, () -> selected(client, parameters));
    }

    private static void query(SelectiveJdbcClient client, Template template, Parameters parameters) {
        client.query(template, parameters, (row, index) -> row.getInt(1));
    }

    private void denied(Code code, Runnable operation) {
        int prepares = probe.prepares();
        int connections = probe.connections();
        try {
            operation.run();
            throw new AssertionError();
        } catch (Denied denial) {
            require(denial.code() == code && denial.getCause() == null);
        }
        require(probe.prepares() == prepares && probe.connections() == connections);
    }

    private Evidence createProof(Plan plan, String digest) {
        return new Evidence(EVIDENCE_ID, digest, template.queryId(), Rewrite.fingerprint(template.sql()), environment,
                Rewrite.fingerprint(plan.sql()), Rewrite.planFingerprint(plan), VERIFIED_AT, VALID_UNTIL,
                Set.of(Check.values()));
    }

    private static Approval createApproval(Evidence proof) {
        return new Approval(proof.queryId(), proof.sourceFingerprint(), proof.environment(), proof.targetFingerprint(),
                proof.planFingerprint(), proof.id(), proof.digest(), proof.validUntil());
    }

    private static Registry registry(Approval approval, Evidence evidence, Instant now) {
        return new Registry(Map.of(approval.queryId(), approval), Map.of(evidence.id(), evidence), clock(now));
    }

    private static Clock clock(Instant instant) {
        return Clock.fixed(instant, ZoneOffset.UTC);
    }

    private String evidenceDigest(Plan plan, String resultDigest, boolean sourceSqlExecuted) {
        FramedDigest digest = new FramedDigest();
        for (String field : List.of("udak-phase5-equivalence-v1", EVIDENCE_ID, template.queryId(),
                environment.source().name(), environment.target().name(), environment.sourceVersion(),
                environment.targetVersion(), environment.driverVersion(), environment.schemaVersion(),
                environment.providerVersion(), environment.runtimeVersion(), Rewrite.fingerprint(template.sql()),
                Rewrite.fingerprint(plan.sql()), Rewrite.planFingerprint(plan), resultDigest,
                VERIFIED_AT.toString(), VALID_UNTIL.toString(), Boolean.toString(sourceSqlExecuted))) {
            digest.field(field);
        }
        for (Check check : Check.values()) digest.field(check.name());
        return digest.hex();
    }

    private static String resultsDigest(List<List<Row>> pages) {
        FramedDigest digest = new FramedDigest();
        digest.field("udak-phase5-results-v1");
        digest.field("id");
        digest.field("INTEGER");
        digest.field("name");
        digest.field("VARCHAR");
        digest.number(pages.size());
        for (int i = 0; i < pages.size(); i++) {
            digest.field(PAGES.get(i).id());
            List<Row> rows = pages.get(i);
            digest.number(rows.size());
            for (Row row : rows) {
                digest.number(row.id());
                digest.field(row.name());
            }
        }
        return digest.hex();
    }

    private void require(boolean condition) {
        assertions++;
        if (!condition) throw new AssertionError();
    }

    private static <T> T at(String code, Checked<T> operation) {
        try {
            return operation.run();
        } catch (Failure failure) {
            throw failure;
        } catch (VirtualMachineError | ThreadDeath failure) {
            throw failure;
        } catch (Throwable failure) {
            throw new Failure(code, failure);
        }
    }

    public static final class Failure extends RuntimeException {
        private static final long serialVersionUID = 1L;
        private final List<String> diagnostics;

        Failure(String code) { this(code, null); }

        Failure(String code, Throwable cause) {
            super(code, null, true, false);
            diagnostics = diagnosticsFor(cause);
        }

        public String code() { return getMessage(); }

        public List<String> diagnostics() {
            List<String> result = new ArrayList<>(diagnostics);
            for (Throwable suppressed : getSuppressed()) {
                if (suppressed instanceof Failure failure) {
                    result.add("cleanup " + failure.code());
                    result.addAll(failure.diagnostics);
                }
            }
            return List.copyOf(result);
        }

        private static List<String> diagnosticsFor(Throwable failure) {
            List<String> lines = new ArrayList<>();
            for (int depth = 0; failure != null && depth < 5; depth++, failure = failure.getCause()) {
                String location = "";
                for (StackTraceElement frame : failure.getStackTrace()) {
                    if (frame.getClassName().startsWith("dev.udak.") && frame.getLineNumber() > 0) {
                        location = " at " + frame.getClassName() + ':' + frame.getLineNumber();
                        break;
                    }
                }
                lines.add(failure.getClass().getName() + location);
            }
            return List.copyOf(lines);
        }
    }

    private static final class FramedDigest {
        private final MessageDigest digest;

        FramedDigest() {
            try {
                digest = MessageDigest.getInstance("SHA-256");
            } catch (NoSuchAlgorithmException failure) {
                throw new IllegalStateException("SHA-256 unavailable");
            }
        }

        void number(int value) { digest.update(ByteBuffer.allocate(Integer.BYTES).putInt(value).array()); }

        void field(String value) {
            if (value == null) {
                number(-1);
            } else {
                byte[] bytes = value.getBytes(StandardCharsets.UTF_8);
                number(bytes.length);
                digest.update(bytes);
            }
        }

        String hex() { return HexFormat.of().formatHex(digest.digest()); }
    }

    private static final class LocalH2 {
        static DataSource dataSource() {
            org.h2.jdbcx.JdbcDataSource h2 = new org.h2.jdbcx.JdbcDataSource();
            h2.setURL("jdbc:h2:mem:udak_phase5");
            return h2;
        }
    }

    @FunctionalInterface
    private interface Checked<T> { T run() throws SQLException; }

    @FunctionalInterface
    private interface PagedQuery { List<Row> query(Parameters parameters) throws SQLException; }

    private record Page(String id, Parameters parameters, List<Row> expected) {}
    private record Row(int id, String name) {}
}
