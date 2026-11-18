package dev.udak.observe;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

/** Deterministic public fixtures; only the assertion count is written to output. */
public final class ObserveContractTest {
    private static int assertions;
    private final List<SqlObservation> events = new ArrayList<>();
    private final SqlObserver observer = new SqlObserver(events::add);

    public static void main(String[] args) {
        ObserveContractTest test = new ObserveContractTest();
        test.shapeAndPrivacy();
        test.unavailable();
        test.identity();
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
