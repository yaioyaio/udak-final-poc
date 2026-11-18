package dev.udak.inventory;

import dev.udak.observe.Framework;
import dev.udak.observe.ObservationPoint;
import dev.udak.observe.SqlObservation;
import dev.udak.observe.SqlObserver;

import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.FutureTask;
import java.util.concurrent.TimeUnit;

/** Deterministic contracts using public fixtures and sanitized assertion failures. */
public final class InventoryContractTest {
    private static final String REVISION = "a".repeat(40);
    private static final String PROFILE = "b".repeat(64);
    private static int assertions;

    public static void main(String[] args) throws Exception {
        staticAndObservedMetadata();
        canonicalOrderingAndStableIdentity();
        scopeRestorationAndIsolation();
        boundedCapture();
        inputValidation();
        System.out.println("INVENTORY_CONTRACT PASS");
        System.out.println("ASSERTIONS=" + assertions);
    }

    private static void staticAndObservedMetadata() {
        InventoryCapture capture = new InventoryCapture();
        check(snapshot(capture).equals("{\"schema_version\":1,\"revision\":\"" + REVISION
                + "\",\"profile\":\"" + PROFILE + "\",\"dropped\":0,\"entries\":[]}"));

        capture.declare(Framework.JDBC, "fixture/query/path", "fixture/test/path");
        capture.declare(Framework.JDBC, "fixture/unused/query", null);
        String declared = snapshot(capture);
        check(declared.contains(scoped("fixture/query/path") + ",\"declared\":true,\"observed\":0,\"unavailable\":0"));
        check(declared.contains(scoped("fixture/unused/query") + ",\"declared\":true,\"observed\":0,"
                + "\"unavailable\":0,\"test_ids\":[],\"shapes\":[]"));

        SqlObserver observer = new SqlObserver(capture);
        try (var ignored = capture.scope("fixture/query/path", "fixture/test/path")) {
            jdbc(observer, "select 'fixture-literal'");
            jdbc(observer, "SELECT ?");
            jdbc(observer, "select 'open-fixture");
        }
        jdbc(observer, "select 'different-fixture'");
        observer.observe(Framework.MYBATIS, ObservationPoint.MYBATIS_PREPARE, "fixture-observe-query-id", "select ?");
        String json = snapshot(capture);
        SqlObservation event = jdbcEvent("select ?");
        check(json.contains(scoped("fixture/query/path") + ",\"declared\":true,\"observed\":3,\"unavailable\":1"));
        check(json.contains("\"test_ids\":[\"" + InventoryCapture.hashTestId("fixture/test/path") + "\"]"));
        check(json.contains("\"identity\":\"OBSERVE_ID\",\"query_id_hash\":\"" + event.queryIdHash()
                + "\",\"declared\":false,\"observed\":1,\"unavailable\":0,\"test_ids\":[]"));
        check(occurrences(json, "\"fingerprint_hash\":\"" + event.fingerprintHash() + "\"") == 3);
        check(!json.contains(jdbcEvent(null).fingerprintHash()));
        for (String raw : List.of("fixture/query/path", "fixture/test/path", "fixture-literal",
                "open-fixture", "different-fixture", "select", "SELECT ?", "fixture-observe-query-id")) {
            check(!json.contains(raw));
        }
    }

    private static void canonicalOrderingAndStableIdentity() {
        InventoryCapture first = new InventoryCapture();
        InventoryCapture second = new InventoryCapture();
        captureSample(first, "tests.alpha", "select ? from t", "tests.beta", "select x from t");
        captureSample(second, "tests.beta", "select x from t", "tests.alpha", "select ? from t");
        check(snapshot(first).equals(snapshot(second)));
        String json = snapshot(first);
        check(json.indexOf("\"framework\":\"JDBC\"") < json.indexOf("\"framework\":\"JPA\""));
        check(json.indexOf("\"framework\":\"JPA\"") < json.indexOf("\"framework\":\"MYBATIS\""));
        check(occurrences(json, scoped("sample.query")) == 3);
        check(occurrences(json, "\"fingerprint_hash\"") == 4);
        check(!InventoryCapture.hashQueryId("sample.query").equals(InventoryCapture.hashTestId("sample.query")));
    }

    private static void captureSample(InventoryCapture capture, String firstTest, String firstSql,
                                      String secondTest, String secondSql) {
        SqlObserver observer = new SqlObserver(capture);
        try (var ignored = capture.scope("sample.query", firstTest)) {
            jdbc(observer, firstSql);
            observer.observe(Framework.JPA, ObservationPoint.JPA_INSPECT, null, "select ?");
        }
        try (var ignored = capture.scope("sample.query", secondTest)) {
            jdbc(observer, secondSql);
            observer.observe(Framework.JPA, ObservationPoint.JPA_INSPECT, null, "select ?");
            observer.observe(Framework.MYBATIS, ObservationPoint.MYBATIS_PREPARE, "sample.mapper", "select ?");
        }
        // Match the same MyBatis test coverage regardless of which JDBC observation came first.
        try (var ignored = capture.scope("sample.query", firstTest)) {
            observer.observe(Framework.MYBATIS, ObservationPoint.MYBATIS_PREPARE, "sample.mapper", "select ?");
        }
    }

    private static void scopeRestorationAndIsolation() throws Exception {
        InventoryCapture capture = new InventoryCapture();
        SqlObserver observer = new SqlObserver(capture);
        var outer = capture.scope("outer", "test.outer");
        try (outer) {
            jdbc(observer, "select 1");
            try (var inner = capture.scope("inner", "test.inner")) {
                rejects(IllegalStateException.class, outer::close);
                jdbc(observer, "select 1");
                throw new FixtureFailure();
            } catch (FixtureFailure expected) {
                jdbc(observer, "select 1");
            }
            FutureTask<Boolean> elsewhere = new FutureTask<>(() -> {
                jdbc(observer, "select 1");
                try {
                    outer.close();
                    return false;
                } catch (IllegalStateException expected) {
                    return true;
                }
            });
            Thread worker = new Thread(elsewhere);
            worker.setDaemon(true);
            worker.start();
            check(elsewhere.get(5, TimeUnit.SECONDS));
        }
        outer.close();
        jdbc(observer, "select 1");
        String json = snapshot(capture);
        check(json.contains(scoped("outer") + ",\"declared\":false,\"observed\":2,\"unavailable\":0"));
        check(json.contains(scoped("inner") + ",\"declared\":false,\"observed\":1,\"unavailable\":0"));
        check(json.contains("\"identity\":\"OBSERVE_ID\",\"query_id_hash\":\"" + jdbcEvent("select 1").queryIdHash()
                + "\",\"declared\":false,\"observed\":2,\"unavailable\":0"));

        List<InventoryCapture.Scope> scopes = new ArrayList<>();
        try {
            for (int i = 0; i < 16; i++) scopes.add(capture.scope("depth", null));
            rejects(IllegalStateException.class, () -> capture.scope("over-depth", null));
        } finally {
            for (int i = scopes.size() - 1; i >= 0; i--) scopes.get(i).close();
        }
    }

    private static void boundedCapture() {
        InventoryCapture entries = new InventoryCapture();
        SqlObserver observer = new SqlObserver(entries);
        for (int i = 0; i < 128; i++) entries.declare(Framework.JPA, "static.query." + i, null);
        entries.declare(Framework.JPA, "static.query.limit", null);
        jdbc(observer, "select 1");
        entries.declare(Framework.JPA, "static.query.0", "retained.test");
        String json = snapshot(entries);
        check(occurrences(json, "\"query_id_hash\"") == 128);
        check(json.contains("\"dropped\":2"));
        check(json.contains(InventoryCapture.hashTestId("retained.test")));

        InventoryCapture references = new InventoryCapture();
        SqlObserver referenceObserver = new SqlObserver(references);
        for (int i = 0; i < 8; i++) {
            try (var ignored = references.scope("bounded", "test." + i)) {
                jdbc(referenceObserver, "select sample" + i);
            }
        }
        try (var ignored = references.scope("bounded", "test.0")) {
            jdbc(referenceObserver, "select rejected_shape");
            jdbc(referenceObserver, "select sample0");
        }
        try (var ignored = references.scope("bounded", "rejected.test")) {
            jdbc(referenceObserver, "select sample0");
        }
        references.declare(Framework.JDBC, "bounded", "rejected.declaration");
        references.declare(Framework.JDBC, "bounded", "test.0");
        json = snapshot(references);
        check(occurrences(json, "\"fingerprint_hash\"") == 8);
        check(json.contains("\"dropped\":3"));
        check(json.contains("\"declared\":true,\"observed\":9,\"unavailable\":0"));
        check(!json.contains(InventoryCapture.hashTestId("rejected.test")));
        check(!json.contains(InventoryCapture.hashTestId("rejected.declaration")));
        check(!json.contains(jdbcEvent("select rejected_shape").fingerprintHash()));
    }

    private static void inputValidation() {
        InventoryCapture capture = new InventoryCapture();
        rejects(IllegalArgumentException.class, () -> capture.scope(null, null));
        rejects(IllegalArgumentException.class, () -> capture.scope("sample", " "));
        rejects(IllegalArgumentException.class, () -> capture.scope("x".repeat(257), null));
        rejects(IllegalArgumentException.class, () -> capture.scope("\uD800", null));
        rejects(IllegalArgumentException.class, () -> capture.declare(null, "sample", null));
        rejects(IllegalArgumentException.class, () -> capture.declare(Framework.JPA, " ", null));
        capture.accept(null);
        check(snapshot(capture).contains("\"dropped\":3,\"entries\":[]"));
        rejects(IllegalArgumentException.class, () -> capture.snapshotJson("A".repeat(40), PROFILE));
        rejects(IllegalArgumentException.class, () -> capture.snapshotJson(REVISION, "z".repeat(64)));
        rejects(IllegalArgumentException.class, () -> capture.snapshotJson(REVISION, "b".repeat(63)));
        check(capture.snapshotJson("f".repeat(64), PROFILE).contains("f".repeat(64)));
    }

    private static void jdbc(SqlObserver observer, String sql) {
        observer.observe(Framework.JDBC, ObservationPoint.JDBC_EXECUTE, null, sql);
    }

    private static SqlObservation jdbcEvent(String sql) {
        List<SqlObservation> events = new ArrayList<>();
        jdbc(new SqlObserver(events::add), sql);
        return events.get(0);
    }

    private static String snapshot(InventoryCapture capture) {
        return capture.snapshotJson(REVISION, PROFILE);
    }

    private static String scoped(String queryId) {
        return "\"identity\":\"SCOPED\",\"query_id_hash\":\"" + InventoryCapture.hashQueryId(queryId) + "\"";
    }

    private static int occurrences(String value, String search) {
        int count = 0;
        for (int i = value.indexOf(search); i >= 0; i = value.indexOf(search, i + search.length())) count++;
        return count;
    }

    private static void rejects(Class<? extends Exception> type, Runnable action) {
        try {
            action.run();
        } catch (Exception failure) {
            check(type.isInstance(failure));
            return;
        }
        throw new AssertionError("Expected rejection at inventory assertion " + (assertions + 1));
    }

    private static void check(boolean condition) {
        if (!condition) throw new AssertionError("Inventory assertion " + (assertions + 1) + " failed");
        assertions++;
    }

    private static final class FixtureFailure extends RuntimeException {}
}
