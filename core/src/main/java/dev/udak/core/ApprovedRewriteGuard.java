package dev.udak.core;
import java.util.Map;
import java.util.Objects;
/**
 * Default deny. Approval ties queryId + exact source SQL hash + source/target vendor + revision.
 * This gate DOES NOT translate SQL; vetted providers can be placed behind this decision.
 */
public final class ApprovedRewriteGuard {
    public record Approval(String queryId, String sourceFingerprint, DbVendor source,
                           DbVendor target, String reviewRevision) {}
    private final Map<String, Approval> approved;
    public ApprovedRewriteGuard(Map<String, Approval> approved) {
        this.approved = Map.copyOf(approved);
    }
    public void requireApproved(String queryId, String sql, DbVendor source,
                                DbVendor target, String reviewRevision) {
        Approval expected = approved.get(queryId);
        if (expected == null || !Objects.equals(expected.sourceFingerprint(), SqlFingerprint.sha256(sql))
                || expected.source() != source || expected.target() != target
                || !Objects.equals(expected.reviewRevision(), reviewRevision)) {
            throw new SecurityException("UDAK rewrite denied: approval mismatch for " + queryId);
        }
    }
}
