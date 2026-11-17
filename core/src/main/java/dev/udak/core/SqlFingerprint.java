package dev.udak.core;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HexFormat;
public final class SqlFingerprint {
    private SqlFingerprint() {}
    /** Exact UTF-8 content digest; whitespace changes intentionally invalidate approval. */
    public static String sha256(String rawSql) {
        try {
            byte[] hash = MessageDigest.getInstance("SHA-256").digest(rawSql.getBytes(StandardCharsets.UTF_8));
            return HexFormat.of().formatHex(hash);
        } catch (NoSuchAlgorithmException ex) { throw new IllegalStateException(ex); }
    }
}
