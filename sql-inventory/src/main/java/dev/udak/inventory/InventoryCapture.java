package dev.udak.inventory;

import dev.udak.observe.FingerprintStatus;
import dev.udak.observe.Framework;
import dev.udak.observe.ObservationSink;
import dev.udak.observe.SqlObservation;
import dev.udak.observe.StatementKind;
import dev.udak.observe.UnavailableReason;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.Comparator;
import java.util.EnumMap;
import java.util.HexFormat;
import java.util.Iterator;
import java.util.Map;
import java.util.Set;
import java.util.TreeMap;
import java.util.TreeSet;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.locks.ReentrantLock;
import java.util.regex.Pattern;

/** Bounded, metadata-only SQL observation for explicitly managed test scenarios. */
public final class InventoryCapture implements ObservationSink {
    private static final int MAX_ENTRIES = 128;
    private static final int MAX_REFERENCES = 8;
    private static final int MAX_SCOPE_DEPTH = 16;
    private static final int MAX_ID_LENGTH = 256;
    private static final Pattern REVISION = Pattern.compile("[0-9a-f]{40}(?:[0-9a-f]{24})?");
    private static final Pattern DIGEST = Pattern.compile("[0-9a-f]{64}");
    private static final Comparator<Key> KEY_ORDER = Comparator.comparing((Key key) -> key.framework().name())
            .thenComparing(key -> key.identity().name()).thenComparing(Key::queryIdHash);

    private final ThreadLocal<Scope> scope = new ThreadLocal<>();
    private final ReentrantLock lock = new ReentrantLock();
    private final TreeMap<Key, Entry> entries = new TreeMap<>(KEY_ORDER);
    private final AtomicInteger dropped = new AtomicInteger();

    /**
     * Binds a logical query and optional test ID to observations on the calling thread until closed.
     * Nest scopes with try-with-resources to restore the enclosing scope even when the query fails.
     */
    public Scope scope(String queryId, String testId) {
        Scope previous = currentScope();
        int depth = previous == null ? 1 : previous.depth + 1;
        if (depth > MAX_SCOPE_DEPTH) throw new IllegalStateException("Inventory scope limit reached");
        Scope current = new Scope(hashQueryId(queryId), optionalTestHash(testId), previous, depth);
        scope.set(current);
        return current;
    }

    /** Registers a known logical query and its optional test without implying runtime observation. */
    public void declare(Framework framework, String queryId, String testId) {
        if (framework == null) {
            drop();
            throw new IllegalArgumentException("Inventory framework required");
        }
        String queryHash;
        String testHash;
        try {
            queryHash = hashQueryId(queryId);
            testHash = optionalTestHash(testId);
        } catch (IllegalArgumentException invalid) {
            drop();
            throw invalid;
        }
        if (!lock.tryLock()) {
            drop();
            return;
        }
        try {
            Entry entry = findOrCreate(new Key(framework, Identity.SCOPED, queryHash));
            if (entry == null || !entry.canAddTest(testHash)) {
                drop();
                return;
            }
            entry.addTest(testHash);
            entry.declared = true;
        } finally {
            lock.unlock();
        }
    }

    @Override
    public void accept(SqlObservation event) {
        accept(event, event != null && event.fingerprintStatus() == FingerprintStatus.UNAVAILABLE
                ? UnavailableReason.UNSPECIFIED : UnavailableReason.NONE);
    }

    @Override
    public void accept(SqlObservation event, UnavailableReason reason) {
        if (event == null || reason == null
                || (event.fingerprintStatus() == FingerprintStatus.NORMALIZED) != (reason == UnavailableReason.NONE)
                || !lock.tryLock()) {
            drop();
            return;
        }
        try {
            Scope active = currentScope();
            Key key = active == null
                    ? new Key(event.framework(), Identity.OBSERVE_ID, event.queryIdHash())
                    : new Key(event.framework(), Identity.SCOPED, active.queryIdHash);
            String testHash = active == null ? null : active.testIdHash;
            Entry entry = findOrCreate(key);
            if (entry == null || !entry.record(event, reason, testHash)) drop();
        } finally {
            lock.unlock();
        }
    }

    /**
     * Serializes a canonical version 1 snapshot after all producers have finished.
     * Revision and profile must be lowercase hexadecimal digests supplied by the caller.
     */
    public String snapshotJson(String revision, String profile) {
        return snapshotJson(revision, profile, false);
    }

    /**
     * Serializes a version 2 snapshot with test hashes for each shape observed in a test scope.
     * Revision and profile must be lowercase hexadecimal digests supplied by the caller.
     */
    public String snapshotJsonWithObservedTests(String revision, String profile) {
        return snapshotJson(revision, profile, true);
    }

    private String snapshotJson(String revision, String profile, boolean includeObservedTests) {
        if (revision == null || (revision.length() != 40 && revision.length() != 64)
                || !REVISION.matcher(revision).matches() || profile == null || profile.length() != 64
                || !DIGEST.matcher(profile).matches()) {
            throw new IllegalArgumentException("Invalid inventory snapshot metadata");
        }
        lock.lock();
        try {
            StringBuilder json = new StringBuilder();
            json.append("{\"schema_version\":").append(includeObservedTests ? 2 : 1)
                    .append(",\"revision\":\"").append(revision)
                    .append("\",\"profile\":\"").append(profile)
                    .append("\",\"dropped\":").append(dropped.get()).append(",\"entries\":[");
            Iterator<Map.Entry<Key, Entry>> iterator = entries.entrySet().iterator();
            while (iterator.hasNext()) {
                Map.Entry<Key, Entry> item = iterator.next();
                item.getValue().appendJson(json, item.getKey(), includeObservedTests);
                if (iterator.hasNext()) json.append(',');
            }
            return json.append("]}").toString();
        } finally {
            lock.unlock();
        }
    }

    public static String hashQueryId(String queryId) {
        return hashId("udak-inventory-query-id-v1", queryId);
    }

    public static String hashTestId(String testId) {
        return hashId("udak-inventory-test-id-v1", testId);
    }

    private static String optionalTestHash(String testId) {
        return testId == null ? null : hashTestId(testId);
    }

    private static String hashId(String domain, String value) {
        if (value == null || value.length() > MAX_ID_LENGTH || value.isBlank()
                || !StandardCharsets.UTF_8.newEncoder().canEncode(value)) {
            throw new IllegalArgumentException("Invalid inventory identifier");
        }
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            digest.update(domain.getBytes(StandardCharsets.US_ASCII));
            digest.update((byte) 0);
            return HexFormat.of().formatHex(digest.digest(value.getBytes(StandardCharsets.UTF_8)));
        } catch (NoSuchAlgorithmException unavailable) {
            throw new IllegalStateException("Inventory digest unavailable");
        }
    }

    private Entry findOrCreate(Key key) {
        Entry entry = entries.get(key);
        if (entry == null && entries.size() < MAX_ENTRIES) {
            entry = new Entry();
            entries.put(key, entry);
        }
        return entry;
    }

    private Scope currentScope() {
        Scope current = scope.get();
        if (current == null) scope.remove();
        return current;
    }

    private void drop() {
        dropped.getAndUpdate(value -> value == Integer.MAX_VALUE ? value : value + 1);
    }

    public final class Scope implements AutoCloseable {
        private final String queryIdHash;
        private final String testIdHash;
        private final int depth;
        private volatile Thread owner = Thread.currentThread();
        private Scope previous;

        private Scope(String queryIdHash, String testIdHash, Scope previous, int depth) {
            this.queryIdHash = queryIdHash;
            this.testIdHash = testIdHash;
            this.previous = previous;
            this.depth = depth;
        }

        @Override
        public void close() {
            if (owner == null) return;
            if (owner != Thread.currentThread() || scope.get() != this) {
                throw new IllegalStateException("Inventory scopes must close in order on their creating thread");
            }
            if (previous == null) scope.remove();
            else scope.set(previous);
            previous = null;
            owner = null;
        }
    }

    private enum Identity { SCOPED, OBSERVE_ID }

    private record Key(Framework framework, Identity identity, String queryIdHash) {}

    private static void appendTestIds(StringBuilder json, Set<String> testIds) {
        json.append(",\"test_ids\":[");
        Iterator<String> tests = testIds.iterator();
        while (tests.hasNext()) {
            json.append('"').append(tests.next()).append('"');
            if (tests.hasNext()) json.append(',');
        }
        json.append(']');
    }

    private static final class Shape {
        private final StatementKind statementKind;
        private Set<String> testIds = Set.of();

        private Shape(StatementKind statementKind) {
            this.statementKind = statementKind;
        }

        private void addTest(String testHash) {
            if (testHash == null) return;
            if (testIds.isEmpty()) testIds = new TreeSet<>();
            testIds.add(testHash);
        }
    }

    private static final class Entry {
        private final TreeSet<String> testIds = new TreeSet<>();
        private final TreeMap<String, Shape> shapes = new TreeMap<>();
        private boolean declared;
        private int observed;
        private int unavailable;
        private EnumMap<UnavailableReason, Integer> unavailableReasons;

        private boolean canAddTest(String testHash) {
            return testHash == null || testIds.size() < MAX_REFERENCES || testIds.contains(testHash);
        }

        private void addTest(String testHash) {
            if (testHash != null) testIds.add(testHash);
        }

        private boolean record(SqlObservation event, UnavailableReason reason, String testHash) {
            if (observed == Integer.MAX_VALUE || !canAddTest(testHash)) return false;
            if (event.fingerprintStatus() == FingerprintStatus.UNAVAILABLE) {
                unavailable++;
                if (unavailableReasons == null) unavailableReasons = new EnumMap<>(UnavailableReason.class);
                unavailableReasons.merge(reason, 1, Integer::sum);
            } else {
                String fingerprint = event.fingerprintHash();
                Shape shape = shapes.get(fingerprint);
                if (shape == null) {
                    if (shapes.size() == MAX_REFERENCES) return false;
                    shape = new Shape(event.statementKind());
                    shapes.put(fingerprint, shape);
                } else if (shape.statementKind != event.statementKind()) {
                    return false;
                }
                // canAddTest bounds each shape's references through the entry's test IDs.
                shape.addTest(testHash);
            }
            observed++;
            addTest(testHash);
            return true;
        }

        private void appendJson(StringBuilder json, Key key, boolean includeObservedTests) {
            json.append("{\"framework\":\"").append(key.framework().name())
                    .append("\",\"identity\":\"").append(key.identity().name())
                    .append("\",\"query_id_hash\":\"").append(key.queryIdHash())
                    .append("\",\"declared\":").append(declared)
                    .append(",\"observed\":").append(observed)
                    .append(",\"unavailable\":").append(unavailable);
            appendTestIds(json, testIds);
            json.append(",\"shapes\":[");
            Iterator<Map.Entry<String, Shape>> fingerprints = shapes.entrySet().iterator();
            while (fingerprints.hasNext()) {
                Map.Entry<String, Shape> shape = fingerprints.next();
                json.append("{\"fingerprint_hash\":\"").append(shape.getKey())
                        .append("\",\"statement_kind\":\"").append(shape.getValue().statementKind.name()).append('"');
                if (includeObservedTests) appendTestIds(json, shape.getValue().testIds);
                json.append('}');
                if (fingerprints.hasNext()) json.append(',');
            }
            json.append(']');
            if (unavailableReasons != null) {
                json.append(",\"unavailable_reasons\":{");
                Iterator<Map.Entry<UnavailableReason, Integer>> reasons = unavailableReasons.entrySet().iterator();
                while (reasons.hasNext()) {
                    Map.Entry<UnavailableReason, Integer> reason = reasons.next();
                    json.append('"').append(reason.getKey().name()).append("\":").append(reason.getValue());
                    if (reasons.hasNext()) json.append(',');
                }
                json.append('}');
            }
            json.append('}');
        }
    }
}
