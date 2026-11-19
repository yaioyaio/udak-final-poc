package dev.udak.observe;

import java.security.MessageDigest;
import java.util.Objects;

/** Emits metadata synchronously. A sink must return promptly and own its concurrency policy. */
public final class SqlObserver {
    private static final int MAX_QUERY_ID_LENGTH = 256;
    private final ObservationSink sink;
    private volatile SourceId lastSourceId;

    private record SourceId(Framework framework, String fingerprint, String hash) {}

    public SqlObserver(ObservationSink sink) {
        this.sink = Objects.requireNonNull(sink, "Observation sink required");
    }

    /** Nonfatal observation failures are isolated. VM errors and ThreadDeath propagate. */
    public void observe(Framework framework, ObservationPoint point, String queryId, String sql) {
        try {
            MessageDigest digest = ObservationDigest.newSha256();
            SqlShape shape = SqlShape.parse(sql, digest);
            String id = queryId == null || queryId.length() > MAX_QUERY_ID_LENGTH || queryId.isBlank()
                    ? sourceId(framework, shape.hash(), digest)
                    : ObservationDigest.QUERY_ID.hash(digest, queryId);
            sink.accept(new SqlObservation(framework, point, id, shape.hash(), shape.kind(), shape.status()));
        } catch (VirtualMachineError | ThreadDeath fatal) {
            throw fatal;
        } catch (Throwable ignored) {
            if (ignored instanceof InterruptedException) Thread.currentThread().interrupt();
            // A diagnostic failure must not change the result or expose exception details.
        }
    }

    private String sourceId(Framework framework, String fingerprint, MessageDigest digest) {
        SourceId cached = lastSourceId;
        if (cached != null && cached.framework() == framework && cached.fingerprint().equals(fingerprint)) {
            return cached.hash();
        }
        String hash = ObservationDigest.SOURCE_SHAPE.hash(digest, framework.name() + ":" + fingerprint);
        lastSourceId = new SourceId(framework, fingerprint, hash);
        return hash;
    }
}
