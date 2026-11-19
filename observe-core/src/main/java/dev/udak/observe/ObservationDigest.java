package dev.udak.observe;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HexFormat;

enum ObservationDigest {
    SQL_SHAPE("sql-shape"), UNAVAILABLE("unavailable"), SOURCE_SHAPE("source-shape"), QUERY_ID("query-id");

    private final byte[] prefix;

    ObservationDigest(String domain) {
        prefix = (domain + '\0').getBytes(StandardCharsets.US_ASCII);
    }

    static MessageDigest newSha256() {
        try {
            return MessageDigest.getInstance("SHA-256");
        } catch (NoSuchAlgorithmException unavailable) {
            throw new IllegalStateException("Observation digest unavailable");
        }
    }

    String hash(MessageDigest digest, String value) {
        digest.update(prefix);
        // digest(byte[]) completes the hash and resets the engine for the next domain.
        return HexFormat.of().formatHex(digest.digest(value.getBytes(StandardCharsets.UTF_8)));
    }
}
