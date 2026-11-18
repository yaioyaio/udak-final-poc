package dev.udak.observe;

/** Immutable metadata. Shape hashes may collide across SQL forms and are solely for observation. */
public record SqlObservation(Framework framework, ObservationPoint point,
                             String queryIdHash, String fingerprintHash,
                             StatementKind statementKind, FingerprintStatus fingerprintStatus) {
    public SqlObservation {
        if (framework == null || point == null || statementKind == null || fingerprintStatus == null
                || !validDigest(queryIdHash) || !validDigest(fingerprintHash)) {
            throw new IllegalArgumentException("Invalid SQL observation metadata");
        }
        Framework expected = switch (point) {
            case JPA_INSPECT -> Framework.JPA;
            case MYBATIS_PREPARE -> Framework.MYBATIS;
            case JDBC_EXECUTE -> Framework.JDBC;
        };
        if (framework != expected) {
            throw new IllegalArgumentException("Inconsistent SQL observation source");
        }
    }

    private static boolean validDigest(String digest) {
        if (digest == null || digest.length() != 64) return false;
        for (int i = 0; i < digest.length(); i++) {
            char c = digest.charAt(i);
            if (!(c >= '0' && c <= '9' || c >= 'a' && c <= 'f')) return false;
        }
        return true;
    }
}
