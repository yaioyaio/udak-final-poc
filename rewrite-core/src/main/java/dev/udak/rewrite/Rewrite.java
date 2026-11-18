package dev.udak.rewrite;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.Clock;
import java.time.Instant;
import java.util.ArrayList;
import java.util.EnumSet;
import java.util.HashMap;
import java.util.HexFormat;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.function.Function;
import java.util.regex.Pattern;

/** Explicit approval policy for translation of a single, exact SQL template. */
public final class Rewrite {
    private static final Pattern ID = Pattern.compile("[A-Za-z0-9][A-Za-z0-9._:+-]{0,127}");
    private static final Pattern VERSION = Pattern.compile("[A-Za-z0-9][A-Za-z0-9._:+-]{0,63}");
    private static final Pattern HASH = Pattern.compile("[A-Fa-f0-9]{64}");
    private static final Pattern COLUMN = Pattern.compile("[A-Za-z_][A-Za-z0-9_]{0,127}");
    private static final Set<Check> REQUIRED = Set.copyOf(EnumSet.allOf(Check.class));

    private Rewrite() {}

    public enum Dialect { H2, POSTGRESQL, MYSQL, SQLSERVER, ORACLE }
    public enum Role { FILTER, LIMIT, OFFSET }
    public enum Check { SOURCE_ROWS, TARGET_ROWS, BIND_ORDER, RESULT_LABELS, TRANSACTION, NEGATIVE }
    public enum Code {
        INVALID_INPUT, MISSING_APPROVAL, EXPIRED, REVOKED, MISMATCH, EVIDENCE_INVALID,
        PROVIDER_FAILED, PLAN_MISMATCH, UNSUPPORTED
    }

    public static final class Denied extends SecurityException {
        private static final long serialVersionUID = 1L;
        private final Code code;

        public Denied(Code code) {
            super("Rewrite denied", null);
            this.code = code == null ? Code.INVALID_INPUT : code;
        }

        public Code code() { return code; }
    }

    public record Environment(Dialect source, Dialect target, String sourceVersion, String targetVersion,
                              String driverVersion, String schemaVersion, String providerVersion,
                              String runtimeVersion) {
        public Environment {
            required(source);
            required(target);
            token(sourceVersion, VERSION);
            token(targetVersion, VERSION);
            token(driverVersion, VERSION);
            token(schemaVersion, VERSION);
            token(providerVersion, VERSION);
            token(runtimeVersion, VERSION);
        }
        @Override public String toString() { return "Environment[redacted]"; }
    }

    public record Template(String queryId, String sql, Environment environment) {
        public Template {
            token(queryId, ID);
            validateSql(sql);
            required(environment);
        }
        @Override public String toString() { return "Template[redacted]"; }
    }

    public record Plan(String sql, List<Role> bindOrder, List<String> columns) {
        public Plan {
            validateSql(sql);
            bindOrder = snapshot(bindOrder, Role.values().length);
            if (bindOrder.size() != Role.values().length || !bindOrder.containsAll(List.of(Role.values()))) {
                throw new Denied(Code.INVALID_INPUT);
            }
            columns = snapshot(columns, 32);
            for (String column : columns) token(column, COLUMN);
        }
        @Override public String toString() { return "Plan[redacted]"; }
    }

    public interface Provider {
        String version();
        Plan translate(Template template);
    }

    /** The registering caller verifies the artifact bytes and issues this immutable attestation. */
    public record Evidence(String id, String digest, String queryId, String sourceFingerprint,
                           Environment environment, String targetFingerprint, String planFingerprint,
                           Instant verifiedAt, Instant validUntil, Set<Check> passed) {
        public Evidence {
            token(id, ID);
            digest = hash(digest);
            token(queryId, ID);
            sourceFingerprint = hash(sourceFingerprint);
            required(environment);
            targetFingerprint = hash(targetFingerprint);
            planFingerprint = hash(planFingerprint);
            required(verifiedAt);
            required(validUntil);
            EnumSet<Check> copy = EnumSet.noneOf(Check.class);
            for (Check check : required(passed)) copy.add(required(check));
            passed = Set.copyOf(copy);
        }
        @Override public String toString() { return "Evidence[redacted]"; }
    }

    public record Approval(String queryId, String sourceFingerprint, Environment environment,
                           String targetFingerprint, String planFingerprint, String evidenceId,
                           String evidenceDigest, Instant expiresAt) {
        public Approval {
            token(queryId, ID);
            sourceFingerprint = hash(sourceFingerprint);
            required(environment);
            targetFingerprint = hash(targetFingerprint);
            planFingerprint = hash(planFingerprint);
            token(evidenceId, ID);
            evidenceDigest = hash(evidenceDigest);
            required(expiresAt);
        }
        @Override public String toString() { return "Approval[redacted]"; }
    }

    public static String fingerprint(String sql) {
        validateSql(sql);
        return HexFormat.of().formatHex(sha256().digest(sql.getBytes(StandardCharsets.UTF_8)));
    }

    /** Each UTF-8 field has a big-endian 32-bit byte length. Both lists have 32-bit element counts. */
    public static String planFingerprint(Plan plan) {
        required(plan);
        MessageDigest digest = sha256();
        field(digest, plan.sql());
        number(digest, plan.bindOrder().size());
        for (Role role : plan.bindOrder()) field(digest, role.name());
        number(digest, plan.columns().size());
        for (String label : plan.columns()) field(digest, label);
        return HexFormat.of().formatHex(digest.digest());
    }

    /** Immutable registered snapshots, with per-query revocation for the lifetime of this registry. */
    public static final class Registry {
        private final Map<String, Approval> approvals;
        private final Map<String, Approval> active;
        private final Map<String, Evidence> evidence;
        private final Clock clock;

        public Registry(Map<String, Approval> approvals, Map<String, Evidence> evidence, Clock clock) {
            this.approvals = index(approvals, Approval::queryId);
            this.active = new HashMap<>(this.approvals);
            this.evidence = index(evidence, Evidence::id);
            this.clock = required(clock);
        }

        public synchronized void revoke(String queryId) {
            token(queryId, ID);
            active.remove(queryId);
        }

        /**
         * The last synchronized authorization check linearizes admission against revoke().
         * Work already admitted can finish after revocation. The executor runs outside the lock.
         */
        public <T> T withApproved(Template template, Provider provider, Function<Plan,T> action) {
            required(template);
            required(provider);
            required(action);
            Approval approval = current(template.queryId());
            if (!approval.environment().equals(template.environment())
                    || !approval.sourceFingerprint().equals(fingerprint(template.sql()))) {
                throw new Denied(Code.MISMATCH);
            }
            Evidence proof = evidence.get(approval.evidenceId());
            if (proof == null || !approval.queryId().equals(proof.queryId())
                    || !approval.evidenceDigest().equals(proof.digest())
                    || !approval.sourceFingerprint().equals(proof.sourceFingerprint())
                    || !approval.environment().equals(proof.environment())
                    || !approval.targetFingerprint().equals(proof.targetFingerprint())
                    || !approval.planFingerprint().equals(proof.planFingerprint())
                    || !proof.passed().equals(REQUIRED)
                    || approval.expiresAt().isAfter(proof.validUntil())) {
                throw new Denied(Code.EVIDENCE_INVALID);
            }
            confirm(approval, proof);
            String version;
            try {
                version = provider.version();
            } catch (Throwable failure) {
                throw providerFailure(failure);
            }
            if (!template.environment().providerVersion().equals(version)) throw new Denied(Code.MISMATCH);

            confirm(approval, proof);
            Plan plan;
            try {
                plan = provider.translate(template);
            } catch (Throwable failure) {
                throw providerFailure(failure);
            }
            if (plan == null || !approval.targetFingerprint().equals(fingerprint(plan.sql()))
                    || !approval.planFingerprint().equals(planFingerprint(plan))) {
                throw new Denied(Code.PLAN_MISMATCH);
            }
            confirm(approval, proof);
            return action.apply(plan);
        }

        private synchronized Approval current(String id) {
            Approval approval = active.get(id);
            if (approval == null) {
                throw new Denied(approvals.containsKey(id) ? Code.REVOKED : Code.MISSING_APPROVAL);
            }
            return approval;
        }

        private synchronized void confirm(Approval approval, Evidence proof) {
            Instant now = clock.instant();
            if (active.get(approval.queryId()) != approval) throw new Denied(Code.REVOKED);
            if (proof.verifiedAt().isAfter(now)) throw new Denied(Code.EVIDENCE_INVALID);
            if (!now.isBefore(approval.expiresAt()) || !now.isBefore(proof.validUntil())) {
                throw new Denied(Code.EXPIRED);
            }
        }

        private static <V> Map<String,V> index(Map<String,V> source, Function<V,String> idOf) {
            Map<String,V> copy = new HashMap<>();
            for (Map.Entry<String,V> entry : required(source).entrySet()) {
                V value = required(entry.getValue());
                String id = idOf.apply(value);
                if (!id.equals(entry.getKey()) || copy.putIfAbsent(id, value) != null) {
                    throw new Denied(Code.INVALID_INPUT);
                }
            }
            return Map.copyOf(copy);
        }
    }

    private static Denied providerFailure(Throwable failure) {
        if (failure instanceof VirtualMachineError fatal) throw fatal;
        if (failure instanceof ThreadDeath fatal) throw fatal;
        if (failure instanceof Denied denied && denied.code() == Code.UNSUPPORTED) {
            return new Denied(Code.UNSUPPORTED);
        }
        return new Denied(Code.PROVIDER_FAILED);
    }

    private static <T> T required(T value) {
        if (value == null) throw new Denied(Code.INVALID_INPUT);
        return value;
    }

    private static <T> List<T> snapshot(List<T> source, int max) {
        if (required(source).isEmpty() || source.size() > max) throw new Denied(Code.INVALID_INPUT);
        List<T> copy = new ArrayList<>();
        for (T item : source) {
            if (copy.size() == max) throw new Denied(Code.INVALID_INPUT);
            copy.add(required(item));
        }
        if (copy.isEmpty()) throw new Denied(Code.INVALID_INPUT);
        return List.copyOf(copy);
    }

    private static void token(String value, Pattern pattern) {
        if (value == null || !pattern.matcher(value).matches()) throw new Denied(Code.INVALID_INPUT);
    }

    private static String hash(String value) {
        token(value, HASH);
        return value.toLowerCase(Locale.ROOT);
    }

    private static void validateSql(String sql) {
        if (sql == null || sql.isEmpty() || sql.length() > 16_384) throw new Denied(Code.INVALID_INPUT);
        // Reject malformed UTF-16 so the UTF-8 encoder cannot collapse distinct SQL strings.
        if (!StandardCharsets.UTF_8.newEncoder().canEncode(sql)) throw new Denied(Code.INVALID_INPUT);
    }

    private static MessageDigest sha256() {
        try {
            return MessageDigest.getInstance("SHA-256");
        } catch (NoSuchAlgorithmException unavailable) {
            throw new IllegalStateException("SHA-256 unavailable");
        }
    }

    private static void field(MessageDigest digest, String value) {
        byte[] bytes = value.getBytes(StandardCharsets.UTF_8);
        number(digest, bytes.length);
        digest.update(bytes);
    }

    private static void number(MessageDigest digest, int number) {
        digest.update((byte) (number >>> 24));
        digest.update((byte) (number >>> 16));
        digest.update((byte) (number >>> 8));
        digest.update((byte) number);
    }
}
