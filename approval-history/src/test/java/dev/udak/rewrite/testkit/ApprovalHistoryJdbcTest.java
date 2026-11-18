package dev.udak.rewrite.testkit;

import static dev.udak.rewrite.testkit.RewriteFixture.TABLE;

import dev.udak.rewrite.ApprovalHistory;
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
import dev.udak.rewrite.Rewrite.Template;
import dev.udak.rewrite.jdbc.ApprovalHistoryJdbcClient;
import dev.udak.rewrite.jdbc.SelectiveJdbcClient.Parameters;
import dev.udak.rewrite.jsqlparser.PaginationRewriteProvider;
import dev.udak.rewrite.testkit.JdbcProbe.Bind;
import java.io.IOException;
import java.io.PrintStream;
import java.nio.file.Path;
import java.sql.Connection;
import java.sql.DatabaseMetaData;
import java.sql.SQLException;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.EnumSet;
import java.util.List;
import java.util.Set;
import org.h2.jdbcx.JdbcDataSource;

public final class ApprovalHistoryJdbcTest {
    private static final Instant NOW = Instant.parse("2026-11-19T00:00:00Z");
    private static final Clock CLOCK = Clock.fixed(NOW, ZoneOffset.UTC);
    private static final String H2_RELEASE = "2.3.232";
    private static final String SOURCE_SQL = "SELECT id, name FROM " + TABLE + " WHERE status = ? ORDER BY id ASC"
            + " LIMIT ? OFFSET ?";
    private static final String TARGET_SQL = "SELECT id AS \"id\", name AS \"name\" FROM " + TABLE
            + " WHERE status = ? ORDER BY id ASC LIMIT ? OFFSET ?";
    private static final Provider PROVIDER = new PaginationRewriteProvider(Set.of(TABLE), Set.of("id", "name", "status"));
    private static final Parameters PAGE = new Parameters("active", 2, 1);
    private static final List<Row> EXPECTED = List.of(new Row(20, null), new Row(30, "charlie"));
    private static int assertions;

    public static void main(String[] args) {
        PrintStream out = RewriteEquivalenceTest.suppressRuntimeOutput();
        try {
            check(args.length == 1, "scratch_argument");
            exercise(Path.of(args[0]).resolve("h2-history.bin"));
            out.println("APPROVAL_HISTORY_H2 PASS");
            out.println("ASSERTIONS=" + assertions);
        } catch (Exception | AssertionError failure) {
            String diagnostic = failure instanceof FailedCheck check ? check.getMessage()
                    : failure.getClass().getSimpleName();
            out.println("APPROVAL_HISTORY_H2 FAIL");
            out.println("DIAGNOSTIC=" + diagnostic);
            System.exit(1);
        }
    }

    private static void exercise(Path journal) throws SQLException, IOException {
        JdbcDataSource source = new JdbcDataSource();
        source.setURL("jdbc:h2:mem:udak_approval_history");
        Environment firstEnvironment;
        Environment nextEnvironment;
        try (Connection connection = source.getConnection()) {
            DatabaseMetaData metadata = connection.getMetaData();
            String database = metadata.getDatabaseProductVersion();
            String driver = metadata.getDriverVersion();
            check("H2".equals(metadata.getDatabaseProductName()), "h2_product");
            check(pinnedRelease(database), "h2_database_release");
            check(pinnedRelease(driver), "h2_driver_release");
            firstEnvironment = environment(database, driver, "schema-1");
            nextEnvironment = environment(database, driver, "schema-2");
        }

        Template first = new Template("approval.h2.page", SOURCE_SQL, firstEnvironment);
        Template other = new Template("approval.h2.other", SOURCE_SQL, firstEnvironment);
        Template next = new Template(first.queryId(), SOURCE_SQL, nextEnvironment);
        Plan plan = PROVIDER.translate(first);
        check(TARGET_SQL.equals(plan.sql()) && !SOURCE_SQL.equals(plan.sql()), "translated_sql");
        JdbcProbe probe = new JdbcProbe(source);
        try (RewriteFixture fixture = new RewriteFixture(source, firstEnvironment)) {
            fixture.create();
            long old;
            try (ApprovalHistory history = ApprovalHistory.open(journal, CLOCK)) {
                ApprovalHistoryJdbcClient client = client(probe, history, first);
                deniedWithoutJdbc(probe, Code.MISSING_APPROVAL, () -> select(client, first), "unapproved_select");
                old = approve(history, first, plan, "h2-first");
                approve(history, other, plan, "h2-other");
                selected(probe, client, first);
                check(history.revoke(first.queryId(), old), "revoked_active_generation");
                deniedWithoutJdbc(probe, Code.REVOKED, () -> select(client, first), "revoked_select");
                selected(probe, client, other);
            }

            try (ApprovalHistory history = ApprovalHistory.open(journal, CLOCK)) {
                ApprovalHistoryJdbcClient replay = client(probe, history, first);
                deniedWithoutJdbc(probe, Code.REVOKED, () -> select(replay, first), "reopened_revoked_select");
                selected(probe, replay, other);
                check(approve(history, next, PROVIDER.translate(next), "h2-next") == old + 1, "new_generation");
                check(!history.revoke(next.queryId(), old), "stale_revoke_preserves_fresh_approval");
                deniedWithoutJdbc(probe, Code.MISMATCH, () -> select(replay, first), "superseded_select");
                selected(probe, client(probe, history, next), next);
            }
        }
    }

    private static boolean pinnedRelease(String version) {
        return version.equals(H2_RELEASE) || version.startsWith(H2_RELEASE + " ");
    }

    private static Environment environment(String database, String driver, String schema) {
        return new Environment(Dialect.POSTGRESQL, Dialect.H2, Rewrite.fingerprint("postgresql-template-17"),
                Rewrite.fingerprint(database), Rewrite.fingerprint(driver), schema, PROVIDER.version(), "runtime-1");
    }

    private static long approve(ApprovalHistory history, Template template, Plan plan, String evidenceId)
            throws IOException {
        String source = Rewrite.fingerprint(template.sql());
        String target = Rewrite.fingerprint(plan.sql());
        String mapping = Rewrite.planFingerprint(plan);
        String digest = Rewrite.fingerprint(evidenceId);
        Evidence evidence = new Evidence(evidenceId, digest, template.queryId(), source, template.environment(),
                target, mapping, NOW.minusSeconds(5), NOW.plusSeconds(60), EnumSet.allOf(Check.class));
        Approval approval = new Approval(template.queryId(), source, template.environment(), target, mapping,
                evidenceId, digest, NOW.plusSeconds(30));
        return history.approve(approval, evidence);
    }

    private static ApprovalHistoryJdbcClient client(JdbcProbe probe, ApprovalHistory history, Template template) {
        return new ApprovalHistoryJdbcClient(probe, template.environment(), history, PROVIDER);
    }

    private static List<Row> select(ApprovalHistoryJdbcClient client, Template template) {
        return client.query(template, PAGE, (rows, row) -> new Row(rows.getInt("id"), rows.getString("name")));
    }

    private static void selected(JdbcProbe probe, ApprovalHistoryJdbcClient client, Template template) {
        int connections = probe.connections();
        int prepares = probe.prepares();
        int closed = probe.closed();
        check(select(client, template).equals(EXPECTED), "expected_fixture_rows");
        check(probe.connections() == connections + 1, "approved_connection_acquired");
        check(probe.prepares() == prepares + 1 && TARGET_SQL.equals(probe.sql()), "approved_target_prepared");
        check(probe.binds().equals(List.of(new Bind("setString", 1, PAGE.filter()), new Bind("setInt", 2, PAGE.limit()),
                new Bind("setInt", 3, PAGE.offset()))), "approved_bind_order");
        check(probe.closed() == closed + 1, "approved_connection_released");
    }

    private static void deniedWithoutJdbc(JdbcProbe probe, Code code, Runnable action, String label) {
        int connections = probe.connections();
        int prepares = probe.prepares();
        try {
            action.run();
            throw new FailedCheck(label);
        } catch (Denied failure) {
            check(failure.code() == code, label);
        }
        check(probe.connections() == connections && probe.prepares() == prepares, "denied_before_jdbc");
    }

    private static void check(boolean condition, String label) {
        if (!condition) throw new FailedCheck(label);
        assertions++;
    }

    private record Row(int id, String name) {}

    private static final class FailedCheck extends AssertionError {
        private static final long serialVersionUID = 1L;

        FailedCheck(String label) { super(label); }
    }
}
