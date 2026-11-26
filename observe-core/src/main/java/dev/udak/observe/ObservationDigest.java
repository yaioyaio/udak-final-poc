package dev.udak.observe;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HexFormat;

enum ObservationDigest {
    SQL_SHAPE("sql-shape"), UNAVAILABLE("unavailable"), SOURCE_SHAPE("source-shape"), QUERY_ID("query-id");

    // This instance is only cloned. All observed inputs go into independent engines.
    private static final MessageDigest SHA256_TEMPLATE = cloneableSha256();
    private final byte[] prefix;

    ObservationDigest(String domain) {
        prefix = (domain + '\0').getBytes(StandardCharsets.US_ASCII);
    }

    static MessageDigest newSha256() {
        if (SHA256_TEMPLATE != null) {
            synchronized (SHA256_TEMPLATE) {
                try {
                    return (MessageDigest) SHA256_TEMPLATE.clone();
                } catch (CloneNotSupportedException ignored) {
                    // A provider can decline cloning. Use its normal construction path.
                }
            }
        }
        return freshSha256();
    }

    private static MessageDigest cloneableSha256() {
        try {
            MessageDigest template = freshSha256();
            template.clone();
            return template;
        } catch (CloneNotSupportedException | IllegalStateException unavailable) {
            return null;
        }
    }

    private static MessageDigest freshSha256() {
        try {
            return MessageDigest.getInstance("SHA-256");
        } catch (NoSuchAlgorithmException unavailable) {
            throw new IllegalStateException("Observation digest unavailable");
        }
    }

    String hash(MessageDigest digest, String value) {
        byte[] bytes = value.getBytes(StandardCharsets.UTF_8);
        return hash(digest, bytes, bytes.length);
    }

    String hash(MessageDigest digest, byte[] value, int length) {
        digest.update(prefix);
        digest.update(value, 0, length);
        return HexFormat.of().formatHex(digest.digest());
    }

    static String hashSourceShape(MessageDigest digest, Framework framework, String fingerprintHash) {
        // Framework names and the lowercase hexadecimal fingerprint are ASCII.
        digest.update(SOURCE_SHAPE.prefix);
        updateAscii(digest, framework.name());
        digest.update((byte) ':');
        updateAscii(digest, fingerprintHash);
        return HexFormat.of().formatHex(digest.digest());
    }

    private static void updateAscii(MessageDigest digest, String value) {
        for (int i = 0; i < value.length(); i++) {
            digest.update((byte) value.charAt(i));
        }
    }
}
