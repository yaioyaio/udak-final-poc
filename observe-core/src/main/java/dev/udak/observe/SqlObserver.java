package dev.udak.observe;

import java.security.MessageDigest;
import java.security.SecureRandom;
import java.util.Arrays;
import java.util.Objects;
import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;

/** Emits metadata synchronously. A sink must return promptly and own its concurrency policy. */
public final class SqlObserver {
    private static final int MAX_QUERY_ID_LENGTH = 256;
    private static final int MAX_JDBC_REUSE_SQL_LENGTH = 1_024;
    private static final String JDBC_TAG_ALGORITHM = "HmacSHA256";
    private final ObservationSink sink;
    private final Object jdbcReuseKeyLock = new Object();
    private volatile SourceId lastSourceId;
    private volatile SecretKeySpec jdbcReuseKey;
    private volatile PreparedJdbcEntry lastJdbcPreparation;

    private record SourceId(Framework framework, String fingerprint, String hash) {}

    private record PreparedJdbcEntry(byte[] tag, PreparedObservation observation) {}

    /** An opaque JDBC observation handle that can be reused across execution attempts. */
    public static final class PreparedObservation {
        private final String queryIdHash;
        private final String fingerprintHash;
        private final StatementKind statementKind;
        private final FingerprintStatus fingerprintStatus;

        private PreparedObservation(String queryIdHash, SqlShape shape) {
            this.queryIdHash = queryIdHash;
            this.fingerprintHash = shape.hash();
            this.statementKind = shape.kind();
            this.fingerprintStatus = shape.status();
        }
    }

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

    /** Prepares metadata for JDBC execution. Returns null if metadata could not be formed. */
    public PreparedObservation prepareJdbc(String sql) {
        try {
            byte[] tag = jdbcReuseTag(sql);
            PreparedJdbcEntry cached = lastJdbcPreparation;
            if (tag != null && cached != null && MessageDigest.isEqual(cached.tag(), tag)) {
                return cached.observation();
            }

            MessageDigest digest = ObservationDigest.newSha256();
            SqlShape shape = SqlShape.parse(sql, digest);
            PreparedObservation prepared = new PreparedObservation(sourceId(Framework.JDBC, shape.hash(), digest),
                    shape);
            if (tag != null) {
                // Keep one preparation per observer. Statements already hold their own metadata handle.
                lastJdbcPreparation = new PreparedJdbcEntry(tag, prepared);
            }
            return prepared;
        } catch (VirtualMachineError | ThreadDeath fatal) {
            throw fatal;
        } catch (Throwable ignored) {
            if (ignored instanceof InterruptedException) Thread.currentThread().interrupt();
            return null;
        }
    }

    /** Emits a fresh event for one JDBC execution attempt. */
    public void observeJdbc(PreparedObservation prepared) {
        if (prepared == null) {
            return;
        }
        try {
            sink.accept(new SqlObservation(Framework.JDBC, ObservationPoint.JDBC_EXECUTE, prepared.queryIdHash,
                    prepared.fingerprintHash, prepared.statementKind, prepared.fingerprintStatus));
        } catch (VirtualMachineError | ThreadDeath fatal) {
            throw fatal;
        } catch (Throwable ignored) {
            if (ignored instanceof InterruptedException) Thread.currentThread().interrupt();
            // A diagnostic failure must not change the result or expose exception details.
        }
    }

    private byte[] jdbcReuseTag(String sql) {
        if (sql == null || sql.isEmpty() || sql.length() > MAX_JDBC_REUSE_SQL_LENGTH) {
            return null;
        }
        byte[] sqlBytes = new byte[sql.length()];
        try {
            for (int i = 0; i < sqlBytes.length; i++) {
                char character = sql.charAt(i);
                if (character > 0x7f) {
                    return null;
                }
                sqlBytes[i] = (byte) character;
            }
            Mac mac = Mac.getInstance(JDBC_TAG_ALGORITHM);
            mac.init(jdbcReuseKey());
            return mac.doFinal(sqlBytes);
        } catch (VirtualMachineError | ThreadDeath fatal) {
            throw fatal;
        } catch (Throwable ignored) {
            if (ignored instanceof InterruptedException) Thread.currentThread().interrupt();
            // Cache failures leave statement-local fingerprinting available.
            return null;
        } finally {
            Arrays.fill(sqlBytes, (byte) 0);
        }
    }

    private SecretKeySpec jdbcReuseKey() {
        SecretKeySpec key = jdbcReuseKey;
        if (key != null) {
            return key;
        }
        synchronized (jdbcReuseKeyLock) {
            if (jdbcReuseKey == null) {
                byte[] keyBytes = new byte[32];
                try {
                    new SecureRandom().nextBytes(keyBytes);
                    jdbcReuseKey = new SecretKeySpec(keyBytes, JDBC_TAG_ALGORITHM);
                } finally {
                    Arrays.fill(keyBytes, (byte) 0);
                }
            }
            return jdbcReuseKey;
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
