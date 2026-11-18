package dev.udak.consistency;

import java.util.ArrayList;
import java.util.EnumSet;
import java.util.List;
import java.util.Objects;

/** Diagnoses the caller's intent and observed transaction state. */
public final class TransactionGuard {
    private TransactionGuard() {
    }

    public enum Severity { INFO, WARNING, ERROR }

    public enum Mode { REPORT_ONLY, BLOCK }

    public enum Propagation {
        REQUIRED, REQUIRES_NEW, NESTED, SUPPORTS, MANDATORY, NEVER, NOT_SUPPORTED
    }

    public enum Isolation {
        DEFAULT, UNKNOWN, READ_UNCOMMITTED, READ_COMMITTED, REPEATABLE_READ, SERIALIZABLE
    }

    public enum Timeout { UNKNOWN, NONE, ACTIVE, EXPIRED }

    public enum Rollback { UNKNOWN, CLEAR, MARKED }

    public enum Outcome { NONE, CONFIRMED_COMMIT, CONFIRMED_ROLLBACK, UNKNOWN }

    public enum Code {
        CONFIGURATION_MISSING(Severity.ERROR),
        MULTIPLE_DATA_SOURCES(Severity.ERROR),
        MISSING_TRANSACTION_MANAGER(Severity.ERROR),
        MULTIPLE_TRANSACTION_MANAGERS(Severity.ERROR),
        UNSUPPORTED_TRANSACTION_MANAGER(Severity.ERROR),
        RESOURCE_MISMATCH(Severity.ERROR),
        ENTITY_MANAGER_FACTORY_MISMATCH(Severity.ERROR),
        UNVERIFIED_ENTITY_MANAGER_FACTORY(Severity.ERROR),
        JPA_REQUIRES_JPA_MANAGER(Severity.ERROR),
        MYBATIS_NOT_SPRING_MANAGED(Severity.ERROR),
        MYBATIS_TEMPLATE_MISMATCH(Severity.ERROR),
        EXISTING_TRANSACTION_VALIDATION_DISABLED(Severity.WARNING),
        NO_ACTUAL_TRANSACTION(Severity.ERROR),
        RESOURCE_NOT_BOUND(Severity.ERROR),
        ENTITY_MANAGER_NOT_BOUND(Severity.ERROR),
        READ_ONLY_WRITE(Severity.ERROR),
        ISOLATION_MISMATCH(Severity.ERROR),
        ISOLATION_UNVERIFIED(Severity.WARNING),
        TIMEOUT_EXPIRED(Severity.ERROR),
        TIMEOUT_UNVERIFIED(Severity.WARNING),
        PARTICIPATING_TIMEOUT_NOT_APPLIED(Severity.WARNING),
        ROLLBACK_ONLY(Severity.ERROR),
        ROLLBACK_UNVERIFIED(Severity.WARNING),
        OUTCOME_UNKNOWN_NO_RETRY(Severity.ERROR),
        REQUIRES_NEW_INDEPENDENT_COMMIT(Severity.WARNING),
        NESTED_JPA_UNSUPPORTED(Severity.ERROR),
        UNEXPECTED_TRANSACTION(Severity.ERROR),
        SYNCHRONIZATION_WITHOUT_TRANSACTION(Severity.WARNING),
        MIXED_ACCESS_REQUIRES_EXPLICIT_FLUSH(Severity.WARNING),
        MIXED_ACCESS_REQUIRES_CACHE_REFRESH(Severity.WARNING),
        TRANSACTION_OWNERSHIP_UNVERIFIED(Severity.WARNING),
        INSPECTION_FAILED(Severity.ERROR);

        private final Severity severity;

        Code(Severity severity) {
            this.severity = severity;
        }

        public Severity severity() {
            return severity;
        }
    }

    /** Propagation and outer transaction presence are declared by the caller. */
    public record Intent(boolean requireTransaction, boolean write, boolean jpaAccess,
                         Propagation propagation, boolean outerTransactionPresent,
                         Isolation requestedIsolation, int requestedTimeoutSeconds,
                         Outcome previousOutcome, boolean retryRequested) {
        public Intent {
            Objects.requireNonNull(propagation, "propagation");
            Objects.requireNonNull(requestedIsolation, "requestedIsolation");
            Objects.requireNonNull(previousOutcome, "previousOutcome");
            if (requestedTimeoutSeconds != -1
                    && (requestedTimeoutSeconds < 1 || requestedTimeoutSeconds > 3600)) {
                throw new IllegalArgumentException("Invalid transaction timeout");
            }
        }
    }

    public record Snapshot(boolean actualTransactionActive, boolean synchronizationActive,
                           boolean resourceBound, boolean entityManagerBound, boolean readOnly,
                           Isolation isolation, Timeout timeout, Rollback rollback) {
        public Snapshot {
            Objects.requireNonNull(isolation, "isolation");
            Objects.requireNonNull(timeout, "timeout");
            Objects.requireNonNull(rollback, "rollback");
        }
    }

    public record Report(List<Code> codes) {
        public Report {
            EnumSet<Code> ordered = EnumSet.noneOf(Code.class);
            ordered.addAll(Objects.requireNonNull(codes, "codes"));
            codes = List.copyOf(ordered);
        }

        public static Report of(Code... codes) {
            return new Report(List.of(codes));
        }

        public Report plus(Report other) {
            List<Code> combined = new ArrayList<>(codes);
            combined.addAll(Objects.requireNonNull(other, "other").codes());
            return new Report(combined);
        }

        public boolean hasErrors() {
            return codes.stream().anyMatch(code -> code.severity() == Severity.ERROR);
        }

        public void requireAllowed() {
            enforce(Mode.BLOCK);
        }

        public void enforce(Mode mode) {
            if (Objects.requireNonNull(mode, "mode") == Mode.BLOCK && hasErrors()) {
                throw new Violation(this);
            }
        }
    }

    public static final class Violation extends IllegalStateException {
        private final Report report;

        private Violation(Report report) {
            super("Transaction Guard blocked the operation", null);
            this.report = report;
        }

        public Report report() {
            return report;
        }
    }

    public static Report assess(Intent intent, Snapshot snapshot) {
        Objects.requireNonNull(intent, "intent");
        Objects.requireNonNull(snapshot, "snapshot");
        List<Code> codes = new ArrayList<>();
        boolean active = snapshot.actualTransactionActive();
        boolean timeoutRequested = intent.requestedTimeoutSeconds() > 0;

        if (!active && (intent.requireTransaction() || intent.propagation() == Propagation.MANDATORY)) {
            codes.add(Code.NO_ACTUAL_TRANSACTION);
        }
        if (intent.requireTransaction() && !snapshot.resourceBound()) {
            codes.add(Code.RESOURCE_NOT_BOUND);
        }
        if (intent.jpaAccess() && active && !snapshot.entityManagerBound()) {
            codes.add(Code.ENTITY_MANAGER_NOT_BOUND);
        }
        if (intent.write() && snapshot.readOnly()) {
            codes.add(Code.READ_ONLY_WRITE);
        }

        Isolation requested = intent.requestedIsolation();
        Isolation observed = snapshot.isolation();
        if (active && requested != Isolation.DEFAULT && requested != Isolation.UNKNOWN) {
            if (observed == Isolation.DEFAULT || observed == Isolation.UNKNOWN) {
                codes.add(Code.ISOLATION_UNVERIFIED);
            } else if (observed != requested) {
                codes.add(Code.ISOLATION_MISMATCH);
            }
        }

        if (snapshot.timeout() == Timeout.EXPIRED) {
            codes.add(Code.TIMEOUT_EXPIRED);
        } else if (timeoutRequested && snapshot.timeout() != Timeout.ACTIVE) {
            codes.add(Code.TIMEOUT_UNVERIFIED);
        }
        if (timeoutRequested && intent.outerTransactionPresent() && switch (intent.propagation()) {
            case REQUIRED, SUPPORTS, MANDATORY -> true;
            default -> false;
        }) {
            codes.add(Code.PARTICIPATING_TIMEOUT_NOT_APPLIED);
        }

        if (snapshot.rollback() == Rollback.MARKED) {
            codes.add(Code.ROLLBACK_ONLY);
        } else if (active && snapshot.rollback() == Rollback.UNKNOWN) {
            codes.add(Code.ROLLBACK_UNVERIFIED);
        }
        if (intent.previousOutcome() == Outcome.UNKNOWN) {
            codes.add(Code.OUTCOME_UNKNOWN_NO_RETRY);
        }

        if (intent.outerTransactionPresent() && intent.propagation() == Propagation.REQUIRES_NEW) {
            codes.add(Code.REQUIRES_NEW_INDEPENDENT_COMMIT);
        }
        if (intent.jpaAccess() && intent.propagation() == Propagation.NESTED) {
            codes.add(Code.NESTED_JPA_UNSUPPORTED);
        }
        if (active && (intent.propagation() == Propagation.NEVER
                || intent.propagation() == Propagation.NOT_SUPPORTED)) {
            codes.add(Code.UNEXPECTED_TRANSACTION);
        }
        if (!active && snapshot.synchronizationActive()) {
            codes.add(Code.SYNCHRONIZATION_WITHOUT_TRANSACTION);
        }
        if (intent.jpaAccess()) {
            codes.add(Code.MIXED_ACCESS_REQUIRES_EXPLICIT_FLUSH);
            codes.add(Code.MIXED_ACCESS_REQUIRES_CACHE_REFRESH);
        }
        if (active) {
            codes.add(Code.TRANSACTION_OWNERSHIP_UNVERIFIED);
        }
        return new Report(codes);
    }
}
