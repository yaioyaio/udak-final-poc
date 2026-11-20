package dev.udak.observe;

import java.security.DigestException;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.util.Arrays;
import java.util.Objects;

/** Emits metadata synchronously. A sink must return promptly and own its concurrency policy. */
public final class SqlObserver {
    private static final int MAX_QUERY_ID_LENGTH = 256;
    private static final int MAX_JDBC_REUSE_SQL_LENGTH = 1_024;
    private static final int JDBC_TAG_KEY_BYTES = 32;
    private final ObservationSink sink;
    private final Object jdbcReuseKeyLock = new Object();
    private volatile SourceId lastSourceId;
    private volatile JdbcReuseKey jdbcReuseKey;
    private volatile PreparedJdbcEntry lastJdbcPreparation;

    private record SourceId(Framework framework, String fingerprint, String hash) {}

    private record PreparedJdbcEntry(byte[] tag, PreparedObservation observation) {}

    static final class JdbcReuseKey {
        private static final int SHA256_BLOCK_BYTES = 64;
        private final byte[] innerPad;
        private final byte[] outerPad;

        JdbcReuseKey(byte[] key) {
            if (key.length != JDBC_TAG_KEY_BYTES) {
                throw new IllegalArgumentException("JDBC tag requires a 32-byte key");
            }
            innerPad = Arrays.copyOf(key, SHA256_BLOCK_BYTES);
            outerPad = Arrays.copyOf(key, SHA256_BLOCK_BYTES);
            for (int i = 0; i < SHA256_BLOCK_BYTES; i++) {
                innerPad[i] ^= 0x36;
                outerPad[i] ^= 0x5c;
            }
        }

        byte[] tag(byte[] sqlBytes) throws DigestException {
            // RFC 2104 HMAC-SHA-256. The pads are fixed, and only this digest receives SQL.
            MessageDigest digest = ObservationDigest.newSha256();
            digest.update(innerPad);
            byte[] tag = digest.digest(sqlBytes);
            try {
                digest.update(outerPad);
                digest.update(tag);
                digest.digest(tag, 0, tag.length);
                return tag;
            } catch (DigestException | RuntimeException | Error failure) {
                Arrays.fill(tag, (byte) 0);
                throw failure;
            }
        }
    }

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
            return jdbcReuseKey().tag(sqlBytes);
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

    private JdbcReuseKey jdbcReuseKey() {
        JdbcReuseKey reuseKey = jdbcReuseKey;
        if (reuseKey != null) {
            return reuseKey;
        }
        synchronized (jdbcReuseKeyLock) {
            if (jdbcReuseKey == null) {
                byte[] keyBytes = new byte[JDBC_TAG_KEY_BYTES];
                try {
                    new SecureRandom().nextBytes(keyBytes);
                    jdbcReuseKey = new JdbcReuseKey(keyBytes);
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
