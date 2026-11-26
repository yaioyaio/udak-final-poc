package dev.udak.observe;

import java.security.MessageDigest;
import java.util.Objects;

/** Emits metadata synchronously. A sink must return promptly and own its concurrency policy. */
public final class SqlObserver {
    private static final int MAX_QUERY_ID_LENGTH = 256;
    private final ObservationSink sink;
    private volatile SqlObservation lastImplicitObservation;

    public SqlObserver(ObservationSink sink) {
        this.sink = Objects.requireNonNull(sink, "Observation sink required");
    }

    /** Nonfatal observation failures are isolated. VM errors and ThreadDeath propagate. */
    public void observe(Framework framework, ObservationPoint point, String queryId, String sql) {
        try {
            MessageDigest digest = ObservationDigest.newSha256();
            SqlShape shape = SqlShape.parse(sql, digest);
            SqlObservation event = queryId == null || queryId.length() > MAX_QUERY_ID_LENGTH || queryId.isBlank()
                    ? implicitObservation(framework, point, shape, digest)
                    : new SqlObservation(framework, point, ObservationDigest.QUERY_ID.hash(digest, queryId),
                            shape.hash(), shape.kind(), shape.status());
            sink.accept(event, shape.reason());
        } catch (VirtualMachineError | ThreadDeath fatal) {
            throw fatal;
        } catch (Throwable ignored) {
            if (ignored instanceof InterruptedException) Thread.currentThread().interrupt();
            // A diagnostic failure must not change the result or expose exception details.
        }
    }

    private SqlObservation implicitObservation(Framework framework, ObservationPoint point,
                                               SqlShape shape, MessageDigest digest) {
        SqlObservation cached = lastImplicitObservation;
        boolean sameSource = cached != null && cached.framework() == framework
                && cached.fingerprintHash().equals(shape.hash());
        FingerprintStatus status = shape.status();
        if (sameSource && cached.point() == point && cached.statementKind() == shape.kind()
                && cached.fingerprintStatus() == status) {
            return cached;
        }
        String id = sameSource ? cached.queryIdHash()
                : ObservationDigest.hashSourceShape(digest, framework, shape.hash());
        SqlObservation event = new SqlObservation(framework, point, id, shape.hash(), shape.kind(), status);
        // Only immutable metadata is reused. Each execution sends its own current reason to the sink.
        lastImplicitObservation = event;
        return event;
    }
}
