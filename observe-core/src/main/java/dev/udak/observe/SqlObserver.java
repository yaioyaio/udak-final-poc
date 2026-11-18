package dev.udak.observe;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HexFormat;
import java.util.Objects;

/** Emits metadata synchronously. A sink must return promptly and own its concurrency policy. */
public final class SqlObserver {
    private static final int MAX_QUERY_ID_LENGTH = 256;
    private final ObservationSink sink;

    public SqlObserver(ObservationSink sink) {
        this.sink = Objects.requireNonNull(sink, "Observation sink required");
    }

    /** Nonfatal observation failures are isolated. VM errors and ThreadDeath propagate. */
    public void observe(Framework framework, ObservationPoint point, String queryId, String sql) {
        try {
            SqlShape shape = SqlShape.parse(sql);
            String id = queryId == null || queryId.length() > MAX_QUERY_ID_LENGTH || queryId.isBlank()
                    ? digest("source-shape", framework.name() + ":" + shape.hash())
                    : digest("query-id", queryId);
            sink.accept(new SqlObservation(framework, point, id, shape.hash(), shape.kind(), shape.status()));
        } catch (VirtualMachineError | ThreadDeath fatal) {
            throw fatal;
        } catch (Throwable ignored) {
            if (ignored instanceof InterruptedException) Thread.currentThread().interrupt();
            // A diagnostic failure must not change the result or expose exception details.
        }
    }

    static String digest(String domain, String value) {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            digest.update(domain.getBytes(StandardCharsets.US_ASCII));
            digest.update((byte) 0);
            return HexFormat.of().formatHex(digest.digest(value.getBytes(StandardCharsets.UTF_8)));
        } catch (NoSuchAlgorithmException unavailable) {
            throw new IllegalStateException("Observation digest unavailable");
        }
    }
}
