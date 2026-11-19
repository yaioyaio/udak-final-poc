package dev.udak.rewrite.testkit;

import dev.udak.rewrite.ApprovalHistory;
import dev.udak.rewrite.Rewrite;
import dev.udak.rewrite.Rewrite.Approval;
import dev.udak.rewrite.Rewrite.Code;
import dev.udak.rewrite.Rewrite.Dialect;
import dev.udak.rewrite.Rewrite.Environment;
import dev.udak.rewrite.Rewrite.Evidence;
import dev.udak.rewrite.Rewrite.Plan;
import dev.udak.rewrite.Rewrite.Template;
import dev.udak.rewrite.jdbc.ApprovalHistoryJdbcClient;
import dev.udak.rewrite.jdbc.SelectiveJdbcClient.Parameters;
import dev.udak.rewrite.jsqlparser.PaginationRewriteProvider;
import java.io.PrintStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.sql.Connection;
import java.sql.DatabaseMetaData;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.Arrays;
import java.util.List;
import java.util.Set;
import org.springframework.jdbc.datasource.DriverManagerDataSource;

/** Limited to the two native loopback fixtures created by the release-support runner. */
public final class ApprovalLiveSupportMain {
    private static final String SQL = "SELECT id, name FROM " + RewriteFixture.TABLE
            + " WHERE status = ? ORDER BY id ASC LIMIT ? OFFSET ?";
    private static final PaginationRewriteProvider PROVIDER = new PaginationRewriteProvider(
            Set.of(RewriteFixture.TABLE), Set.of("id", "name", "status"));
    private static final Parameters PAGE = new Parameters("active", 2, 1);
    private static final List<Row> EXPECTED = List.of(new Row(20, null), new Row(30, "charlie"));
    private static final Instant NOW = Instant.parse("2026-11-18T00:00:00Z");
    private static final Clock CLOCK = Clock.fixed(NOW, ZoneOffset.UTC);

    private record Row(int id, String name) {}

    public static void main(String[] args) {
        PrintStream out = RewriteEquivalenceTest.suppressRuntimeOutput();
        try {
            exercise(args, out);
        } catch (Exception | AssertionError failure) {
            // A JDBC message or cause can contain connection details. Only publish our source line.
            int line = 0;
            for (StackTraceElement frame : failure.getStackTrace()) {
                if (frame.getClassName().equals(ApprovalLiveSupportMain.class.getName())) {
                    line = frame.getLineNumber();
                    break;
                }
            }
            out.println("FIXTURE_ERROR line=" + line);
            System.exit(1);
        }
    }

    private static void exercise(String[] args, PrintStream out) throws Exception {
        require(args.length == 5);
        Dialect target = Dialect.valueOf(args[0]);
        boolean postgres = target == Dialect.POSTGRESQL;
        require(postgres || target == Dialect.MYSQL);
        int port = Integer.parseInt(args[1]);
        require(port > 0 && port <= 65535);
        Path journal = Path.of(args[2]);
        String driverVersion = postgres ? "42.7.14" : "26.10.0";
        DriverManagerDataSource source = source(port, postgres);
        String serverVersion;
        String serverHash;
        String driverHash;
        try (Connection connection = source.getConnection()) {
            DatabaseMetaData metadata = connection.getMetaData();
            require((postgres ? "PostgreSQL" : "MySQL").equals(metadata.getDatabaseProductName()));
            require((postgres ? "PostgreSQL JDBC Driver" : "MySQL Connector/J").equals(metadata.getDriverName()));
            String database = metadata.getDatabaseProductVersion();
            String driver = metadata.getDriverVersion();
            require(postgres ? driver.equals(driverVersion) : driver.startsWith("mysql-connector-j-" + driverVersion + " "));
            serverVersion = database.split("[ -]", 2)[0];
            require(serverVersion.matches("[0-9]{1,3}(\\.[0-9]{1,3}){1,2}"));
            serverHash = Rewrite.fingerprint(database);
            driverHash = Rewrite.fingerprint(driver);
        }
        String sourceHash = postgres ? serverHash : args[3];
        RewriteEquivalenceTest.Summary proof = RewriteEquivalenceTest.run(source, target, serverHash, driverHash, sourceHash);
        require(proof.checks() == RewriteEquivalenceTest.CHECKS.size() && proof.sourceSqlExecuted() == postgres);
        if (!postgres) require(proof.resultDigest().equals(args[4]));
        // Use the query, provider, environment and actual proof digest from the equivalence fixture.
        Environment environment = new Environment(Dialect.POSTGRESQL, target, sourceHash, serverHash, driverHash,
                "p5-schema-1", PROVIDER.version(), "p5-runtime-1");
        Template template = new Template("p5.select-entry-page", SQL, environment);
        Plan plan = PROVIDER.translate(template);
        require(!SQL.equals(plan.sql()));
        JdbcProbe probe = new JdbcProbe(source);
        try (RewriteFixture fixture = new RewriteFixture(source, environment)) {
            fixture.create();
            long first;
            try (ApprovalHistory history = ApprovalHistory.open(journal, CLOCK)) {
                ApprovalHistoryJdbcClient client = new ApprovalHistoryJdbcClient(probe, environment, history, PROVIDER);
                denied(probe, client, template, Code.MISSING_APPROVAL, "MISSING", out);
                first = grant(history, template, plan, proof.evidenceDigest());
                require(first == 1);
                selected(probe, client, template, plan, "FIRST_GRANT", out);
                require(history.revoke(template.queryId(), first));
                denied(probe, client, template, Code.REVOKED, "REVOKED", out);
            }
            try (ApprovalHistory reopened = ApprovalHistory.open(journal, CLOCK)) {
                ApprovalHistoryJdbcClient client = new ApprovalHistoryJdbcClient(probe, environment, reopened, PROVIDER);
                denied(probe, client, template, Code.REVOKED, "REOPENED", out);
                require(grant(reopened, template, plan, proof.evidenceDigest()) == first + 1);
                require(!reopened.revoke(template.queryId(), first));
                selected(probe, client, template, plan, "FRESH_GRANT", out);
            }
        }
        out.println("IDENTITY " + target + " " + serverVersion + " " + driverVersion + " " + serverHash + " " + driverHash);
        out.println("EQUIVALENCE " + proof.resultDigest() + " " + proof.evidenceDigest() + " " + proof.sourceSqlExecuted());
        out.println("CLEANUP CONFIRMED");
    }

    private static DriverManagerDataSource source(int port, boolean postgres) throws Exception {
        byte[] input = System.in.readNBytes(50);
        try {
            require(input.length == 49 && input[48] == '\n');
            String password = new String(input, 0, 48, StandardCharsets.US_ASCII);
            require(password.matches("[0-9a-f]{48}"));
            String url = postgres ? "jdbc:postgresql://127.0.0.1:" + port
                    + "/postgres?currentSchema=public&sslmode=disable&gssEncMode=disable&connectTimeout=5&socketTimeout=5"
                    : "jdbc:mysql://127.0.0.1:" + port + "/udak_fixture?sslMode=DISABLED&connectTimeout=5000"
                    + "&socketTimeout=5000&useInformationSchema=true&logger=com.mysql.cj.log.NullLogger";
            return new DriverManagerDataSource(url, "udak_fixture", password);
        } finally {
            Arrays.fill(input, (byte) 0);
        }
    }

    private static long grant(ApprovalHistory history, Template template, Plan plan, String digest) throws Exception {
        Evidence proof = new Evidence("p5-equivalence-test", digest, template.queryId(), Rewrite.fingerprint(SQL),
                template.environment(), Rewrite.fingerprint(plan.sql()), Rewrite.planFingerprint(plan), NOW,
                NOW.plusSeconds(60), Set.of(Rewrite.Check.values()));
        Approval approval = new Approval(proof.queryId(), proof.sourceFingerprint(), proof.environment(),
                proof.targetFingerprint(), proof.planFingerprint(), proof.id(), proof.digest(), proof.validUntil());
        return history.approve(approval, proof);
    }

    private static List<Row> select(ApprovalHistoryJdbcClient client, Template template) {
        return client.query(template, PAGE, (row, index) -> new Row(row.getInt("id"), row.getString("name")));
    }

    private static void denied(JdbcProbe probe, ApprovalHistoryJdbcClient client, Template template,
                               Code expected, String scenario, PrintStream out) {
        int connections = probe.connections();
        int prepares = probe.prepares();
        try {
            select(client, template);
            throw new AssertionError();
        } catch (Rewrite.Denied failure) {
            require(failure.code() == expected);
        }
        receipt(probe, connections, prepares, 0, scenario, out);
    }

    private static void selected(JdbcProbe probe, ApprovalHistoryJdbcClient client, Template template,
                                 Plan plan, String scenario, PrintStream out) {
        int connections = probe.connections();
        int prepares = probe.prepares();
        int closed = probe.closed();
        require(EXPECTED.equals(select(client, template)));
        require(plan.sql().equals(probe.sql()) && probe.closed() == closed + 1);
        require(probe.binds().equals(List.of(new JdbcProbe.Bind("setString", 1, PAGE.filter()),
                new JdbcProbe.Bind("setInt", 2, PAGE.limit()), new JdbcProbe.Bind("setInt", 3, PAGE.offset()))));
        receipt(probe, connections, prepares, 1, scenario, out);
    }

    private static void receipt(JdbcProbe probe, int connections, int prepares, int expected,
                                String scenario, PrintStream out) {
        int acquired = probe.connections() - connections;
        int prepared = probe.prepares() - prepares;
        require(acquired == expected && prepared == expected);
        out.println("SCENARIO " + scenario + " " + acquired + " " + prepared);
    }

    private static void require(boolean condition) {
        if (!condition) throw new AssertionError();
    }
}
