package dev.udak.observe;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Map;

import static dev.udak.observe.UnavailableReason.*;

/** Deterministic public fixtures; only the assertion count is written to output. */
public final class ObserveContractTest {
    private static int assertions;
    private final List<SqlObservation> events = new ArrayList<>();
    private final SqlObserver observer = new SqlObserver(events::add);

    public static void main(String[] args) {
        ObserveContractTest test = new ObserveContractTest();
        test.shapeAndPrivacy();
        test.unavailable();
        test.unavailableReasons();
        test.identity();
        test.digestCompatibility();
        test.eventsAndFailures();
        System.out.println("Observe contract assertions: " + assertions);
    }

    private void shapeAndPrivacy() {
        SqlObservation baseline = one("select ?");
        check(baseline.statementKind() == StatementKind.SELECT);
        check(baseline.fingerprintStatus() == FingerprintStatus.NORMALIZED);
        for (String literal : List.of("'sample'", "'sam''ple'", "E'sam\\'ple'", "N'sample'",
                "q'[sam''ple]'", "nq'!sam''ple!'", "$$sam'ple$$", "$public_tag$sam'ple$public_tag$",
                "0x1Ac", "0b101", "B'101'", "X'AB'", "-17", "+23", ".42", "2.", "-4.25e+12",
                "false", "true", "null", "$12", ":public_name", "@public_name")) {
            SqlObservation event = one("SELECT " + literal);
            check(event.fingerprintStatus() == FingerprintStatus.NORMALIZED);
            check(event.fingerprintHash().equals(baseline.fingerprintHash()));
        }
        String shape = one("select col from inventory where col = ?").fingerprintHash();
        check(shape.equals(one(" /* outer /* nested */ end */ SELECT Col -- public comment\r\n"
                + " FROM inventory WHERE col=42 ; /* final */").fingerprintHash()));
        check(!shape.equals(one("select col from inventory where col > ?").fingerprintHash()));
        check(!shape.equals(one("select col from inventory_archive where col = ?").fingerprintHash()));
        String quoted = one("select \"public\"\"column\"").fingerprintHash();
        check(quoted.equals(one("select [sample]]column]").fingerprintHash()));
        check(quoted.equals(one("select `another``column`").fingerprintHash()));
        check(one("select 'sample\\folder'").fingerprintHash().equals(baseline.fingerprintHash()));
        check(one("select 'two\\\\'").fingerprintHash().equals(baseline.fingerprintHash()));

        String[] starts = {"INSERT INTO t VALUES (?)", "UPDATE t SET n=?", "DELETE FROM t",
                "MERGE INTO t", "CALL p(?)", "CREATE TABLE t (n INT)", "WITH t AS (SELECT ?) SELECT * FROM t"};
        StatementKind[] expected = {StatementKind.INSERT, StatementKind.UPDATE, StatementKind.DELETE,
                StatementKind.MERGE, StatementKind.CALL, StatementKind.DDL, StatementKind.OTHER};
        for (int i = 0; i < starts.length; i++) check(one(starts[i]).statementKind() == expected[i]);
    }

    private void unavailable() {
        SqlObservation fallback = one(null);
        check(fallback.fingerprintStatus() == FingerprintStatus.UNAVAILABLE);
        check(fallback.statementKind() == StatementKind.UNKNOWN);
        for (String sql : List.of("", "/* only */", "select 'public", "select E'public\\",
                "select 'mode\\'dependent'", "select q'[public'", "select \"public", "select [public",
                "select $tag$public", "select /* open", "select /* ! */ /*! select */ 1",
                "select /*M!version */ 1", "select 0x", "select 1e+", "select 2a", "select 1; select 2",
                "select 1--2", "select x$tag$public$tag$", "select :?", "select #unsupported",
                "select t['part]public[tail']", "alter user public_fixture identified by public_value",
                "exec public_proc @p=public_value", "select (1", "select 1)",
                "select " + "/*".repeat(33) + "*/".repeat(33) + " 1",
                "select '" + "a".repeat(16_384) + "'", "select '" + "b".repeat(16_384) + "'")) {
            check(one(sql).equals(fallback));
        }
        String atLimit = "select 1" + " ".repeat(16_384 - "select 1".length());
        check(one(atLimit).fingerprintStatus() == FingerprintStatus.NORMALIZED);
        check(one(atLimit + " ").equals(fallback));
        check(one("select " + "/*".repeat(32) + "*/".repeat(32) + " 1").fingerprintStatus()
                == FingerprintStatus.NORMALIZED);
    }

    private void unavailableReasons() {
        record ReasonedEvent(SqlObservation event, UnavailableReason reason) {}
        List<ReasonedEvent> diagnostics = new ArrayList<>();
        SqlObserver diagnosticObserver = new SqlObserver(new ObservationSink() {
            @Override
            public void accept(SqlObservation event) {
                throw new AssertionError("Expected reason callback");
            }

            @Override
            public void accept(SqlObservation event, UnavailableReason reason) {
                diagnostics.add(new ReasonedEvent(event, reason));
            }
        });

        SqlObservation legacyFallback = one(null);
        diagnosticObserver.observe(Framework.JDBC, ObservationPoint.JDBC_EXECUTE, null, null);
        check(diagnostics.equals(List.of(new ReasonedEvent(legacyFallback, EMPTY_SQL))));
        Map<UnavailableReason, List<String>> cases = Map.of(
                EMPTY_SQL, List.of("", " \t-- fixture\n /* fixture */ ;"),
                SQL_TOO_LONG, List.of("select 1" + " ".repeat(16_377)),
                MULTIPLE_STATEMENTS, List.of("select 1; /* fixture */ select 2", "select 1;;"),
                AMBIGUOUS_SYNTAX, List.of("select 1--2", "select 'x\\'y'", "select t['x']", "select t$tag$x$tag$"),
                UNSUPPORTED_SYNTAX, List.of("SHOW TABLES", "select #unsupported", "select :?", "select /*! fixture */ 1",
                        "select /*M!fixture */ 1", "exec fixture_proc"),
                MALFORMED_SYNTAX, List.of("select '", "select q'[fixture'", "select 1e+", "select 0x", "select $tag$x",
                        "select /* fixture", "select (1", "select 1)"),
                LEXER_LIMIT, List.of("select " + "/*".repeat(33) + "*/".repeat(33) + " 1",
                        "select $" + "a".repeat(64) + "$x$" + "a".repeat(64) + "$"));
        for (Map.Entry<UnavailableReason, List<String>> casesByReason : cases.entrySet()) {
            for (String sql : casesByReason.getValue()) {
                diagnostics.clear();
                diagnosticObserver.observe(Framework.JDBC, ObservationPoint.JDBC_EXECUTE, null, sql);
                // All rejected inputs share the same cached fallback source ID, independently of the reason.
                check(diagnostics.equals(List.of(new ReasonedEvent(legacyFallback, casesByReason.getKey()))));
            }
        }

        diagnostics.clear();
        String atLimit = "select 1" + " ".repeat(16_376);
        diagnosticObserver.observe(Framework.JDBC, ObservationPoint.JDBC_EXECUTE, null, atLimit);
        check(diagnostics.equals(List.of(new ReasonedEvent(one("select 1"), NONE))));
        diagnostics.clear();
        String queryId = "public.Mapper.find";
        diagnosticObserver.observe(Framework.MYBATIS, ObservationPoint.MYBATIS_PREPARE, queryId, "select (1");
        SqlObservation explicit = one(Framework.MYBATIS, ObservationPoint.MYBATIS_PREPARE, queryId, "select (1");
        check(diagnostics.equals(List.of(new ReasonedEvent(explicit, MALFORMED_SYNTAX))));
    }

    private void identity() {
        SqlObservation first = one(Framework.MYBATIS, ObservationPoint.MYBATIS_PREPARE, "public.Mapper.find", "select 1");
        SqlObservation second = one(Framework.MYBATIS, ObservationPoint.MYBATIS_PREPARE, "public.Mapper.find", "select 2");
        check(first.equals(second));
        check(!second.toString().contains("public.Mapper.find"));
        check(!second.toString().contains("select 2"));
        check(second.queryIdHash().matches("[a-f0-9]{64}"));
        check(second.fingerprintHash().matches("[a-f0-9]{64}"));
        check(!first.queryIdHash().equals(one(Framework.MYBATIS, ObservationPoint.MYBATIS_PREPARE,
                "public.Mapper.other", "select 1").queryIdHash()));
        check(first.queryIdHash().equals(one(Framework.MYBATIS, ObservationPoint.MYBATIS_PREPARE,
                "public.Mapper.find", "update t set n = 1").queryIdHash()));
        check(!one("select 1").queryIdHash().equals(one(Framework.JPA, ObservationPoint.JPA_INSPECT,
                null, "select 1").queryIdHash()));
        SqlObservation implicit = one("select 1");
        check(!implicit.queryIdHash().equals(one("select 1 + 2").queryIdHash()));
        check(implicit.equals(one(Framework.JDBC, ObservationPoint.JDBC_EXECUTE, "x".repeat(257), "select 1")));
        check(implicit.equals(one(Framework.JDBC, ObservationPoint.JDBC_EXECUTE, " ", "select 1")));
        check(!implicit.equals(one(Framework.JDBC, ObservationPoint.JDBC_EXECUTE, "x".repeat(256), "select 1")));
    }

    private void digestCompatibility() {
        SqlObservation jdbc = one("select 1");
        check(jdbc.fingerprintHash().equals("935e32e31a55f2ab83c73cd32a7d8ec3e9b4ad1558fc13f3f918faef5585c8bc"));
        check(jdbc.queryIdHash().equals("dfd89d1b868f4b6d125ec7153b70d1a47f73576f74ba335f3f1e505ab4d54634"));
        check(jdbc.equals(one("select 2")));
        check(one(Framework.JPA, ObservationPoint.JPA_INSPECT, null, "select 3").queryIdHash()
                .equals("38020ece46d4a0dbbcdf9881c32a2943ecf60c0759b68d7e1978e699c946f665"));
        check(one(Framework.JDBC, ObservationPoint.JDBC_EXECUTE, "public.조회", "select 4").queryIdHash()
                .equals("a66d109cc082ac82be0559b26926628c4e71acd929cb6f0e308ebd05aca15958"));
        check(one(null).fingerprintHash().equals("0234e5b0c862f2df5a01eb5474f2dfcec41c204e1aaf6918c694eb65031419b0"));
        check(jdbc.equals(one("select 5")));
    }

    private void eventsAndFailures() {
        check(Arrays.stream(SqlObservation.class.getRecordComponents()).map(c -> c.getType()).toList().equals(
                List.of(Framework.class, ObservationPoint.class, String.class, String.class,
                        StatementKind.class, FingerprintStatus.class)));
        String valid = "a".repeat(64);
        for (String invalid : List.of("public-marker", "A".repeat(64), "a".repeat(63), "g" + valid.substring(1))) {
            try {
                new SqlObservation(Framework.JDBC, ObservationPoint.JDBC_EXECUTE, invalid, valid,
                        StatementKind.SELECT, FingerprintStatus.NORMALIZED);
                throw new AssertionError("Expected metadata rejection");
            } catch (IllegalArgumentException expected) {
                check("Invalid SQL observation metadata".equals(expected.getMessage()));
            }
        }
        events.clear();
        observer.observe(null, null, null, null);
        observer.observe(Framework.JDBC, ObservationPoint.JPA_INSPECT, null, null);
        check(events.isEmpty());
        for (Throwable failure : List.of(new IllegalStateException(), new LinkageError(), new AssertionError())) {
            SqlObserver failing = new SqlObserver(event -> ObserveContractTest.<RuntimeException>raise(failure));
            failing.observe(Framework.JDBC, ObservationPoint.JDBC_EXECUTE, null, "select 1");
            check(true);
        }
        for (Error fatal : List.of(new ThreadDeath(), new VirtualMachineError() {})) {
            try {
                new SqlObserver(event -> { throw fatal; }).observe(
                        Framework.JDBC, ObservationPoint.JDBC_EXECUTE, null, "select 1");
                throw new AssertionError("Expected fatal error");
            } catch (VirtualMachineError | ThreadDeath propagated) {
                check(propagated == fatal);
            }
        }
        new SqlObserver(event -> ObserveContractTest.<RuntimeException>raise(new InterruptedException()))
                .observe(Framework.JDBC, ObservationPoint.JDBC_EXECUTE, null, "select 1");
        check(Thread.currentThread().isInterrupted());
    }

    @SuppressWarnings("unchecked")
    private static <T extends Throwable> void raise(Throwable failure) throws T {
        throw (T) failure;
    }

    private SqlObservation one(String sql) {
        return one(Framework.JDBC, ObservationPoint.JDBC_EXECUTE, null, sql);
    }

    private SqlObservation one(Framework framework, ObservationPoint point, String id, String sql) {
        events.clear();
        observer.observe(framework, point, id, sql);
        check(events.size() == 1);
        return events.get(0);
    }

    private static void check(boolean condition) {
        if (!condition) throw new AssertionError("Observe contract assertion failed");
        assertions++;
    }
}
