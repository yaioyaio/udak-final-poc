package dev.udak.consistency;

import dev.udak.consistency.TransactionGuard.Code;
import dev.udak.consistency.TransactionGuard.Intent;
import dev.udak.consistency.TransactionGuard.Isolation;
import dev.udak.consistency.TransactionGuard.Mode;
import dev.udak.consistency.TransactionGuard.Outcome;
import dev.udak.consistency.TransactionGuard.Propagation;
import dev.udak.consistency.TransactionGuard.Report;
import dev.udak.consistency.TransactionGuard.Rollback;
import dev.udak.consistency.TransactionGuard.Severity;
import dev.udak.consistency.TransactionGuard.Snapshot;
import dev.udak.consistency.TransactionGuard.Timeout;
import dev.udak.consistency.TransactionGuard.Violation;

import java.lang.reflect.ParameterizedType;
import java.lang.reflect.RecordComponent;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.EnumSet;
import java.util.List;

/** Deterministic policy fixtures that print only the assertion count. */
public final class TransactionGuardContractTest {
    private static final Snapshot ACTIVE = new Snapshot(
            true, true, true, false, false, Isolation.READ_COMMITTED, Timeout.NONE, Rollback.CLEAR);
    private static final Snapshot INACTIVE = new Snapshot(
            false, false, false, false, false, Isolation.UNKNOWN, Timeout.UNKNOWN, Rollback.UNKNOWN);
    private static int assertions;

    public static void main(String[] args) {
        reports();
        inputs();
        transactionState();
        isolation();
        propagation();
        timeoutAndOutcome();
        System.out.println("Transaction Guard assertions: " + assertions);
    }

    private static void reports() {
        EnumSet<Code> warnings = EnumSet.of(Code.EXISTING_TRANSACTION_VALIDATION_DISABLED,
                Code.ISOLATION_UNVERIFIED, Code.TIMEOUT_UNVERIFIED, Code.PARTICIPATING_TIMEOUT_NOT_APPLIED,
                Code.ROLLBACK_UNVERIFIED, Code.REQUIRES_NEW_INDEPENDENT_COMMIT,
                Code.SYNCHRONIZATION_WITHOUT_TRANSACTION, Code.MIXED_ACCESS_REQUIRES_EXPLICIT_FLUSH,
                Code.MIXED_ACCESS_REQUIRES_CACHE_REFRESH, Code.TRANSACTION_OWNERSHIP_UNVERIFIED);
        for (Code code : Code.values()) {
            check(code.severity() == (warnings.contains(code) ? Severity.WARNING : Severity.ERROR), "CODE_SEVERITY");
        }

        List<Code> mutable = new ArrayList<>(List.of(
                Code.TIMEOUT_UNVERIFIED, Code.RESOURCE_NOT_BOUND, Code.TIMEOUT_UNVERIFIED));
        Report report = new Report(mutable);
        mutable.clear();
        check(report.codes().equals(List.of(Code.RESOURCE_NOT_BOUND, Code.TIMEOUT_UNVERIFIED)), "REPORT_ORDER");
        expect(UnsupportedOperationException.class, () -> report.codes().clear());
        expect(NullPointerException.class, () -> new Report(null));
        expect(NullPointerException.class, () -> new Report(Arrays.asList(Code.RESOURCE_NOT_BOUND, null)));
        expect(NullPointerException.class, () -> Report.of(Code.RESOURCE_NOT_BOUND, null));
        expect(NullPointerException.class, () -> report.plus(null));
        expect(NullPointerException.class, () -> report.enforce(null));

        Code[] input = { Code.TIMEOUT_EXPIRED };
        Report timeout = Report.of(input);
        input[0] = Code.TIMEOUT_UNVERIFIED;
        check(timeout.codes().equals(List.of(Code.TIMEOUT_EXPIRED)), "REPORT_VARARGS_COPY");
        check(report.plus(timeout).codes().equals(List.of(
                Code.RESOURCE_NOT_BOUND, Code.TIMEOUT_EXPIRED, Code.TIMEOUT_UNVERIFIED)), "REPORT_UNION");
        check(report.plus(timeout).equals(timeout.plus(report)), "REPORT_DETERMINISM");
        check(report.plus(report).equals(report), "REPORT_DEDUPLICATION");
        check(report.hasErrors(), "ERROR_PRESENT");
        report.enforce(Mode.REPORT_ONLY);
        check(report.hasErrors(), "REPORT_ONLY_PRESERVES_ERROR");

        Report warning = Report.of(Code.TIMEOUT_UNVERIFIED);
        warning.requireAllowed();
        Report.of().enforce(Mode.BLOCK);
        check(!warning.hasErrors() && !Report.of().hasErrors(), "ERROR_ABSENT");
        Violation violation = expect(Violation.class, report::requireAllowed);
        check(violation.report() == report, "VIOLATION_REPORT");
        check("Transaction Guard blocked the operation".equals(violation.getMessage()), "VIOLATION_MESSAGE");
        check(violation.getCause() == null && violation.getSuppressed().length == 0, "VIOLATION_CAUSE");
        check(expect(Violation.class, () -> report.enforce(Mode.BLOCK)).report() == report, "BLOCK_REPORT");
    }

    private static void inputs() {
        check(componentTypes(Intent.class).equals(List.of(boolean.class, boolean.class, boolean.class,
                Propagation.class, boolean.class, Isolation.class, int.class, Outcome.class, boolean.class)),
                "INTENT_FIELDS");
        check(componentTypes(Snapshot.class).equals(List.of(boolean.class, boolean.class, boolean.class,
                boolean.class, boolean.class, Isolation.class, Timeout.class, Rollback.class)), "SNAPSHOT_FIELDS");
        RecordComponent[] reportFields = Report.class.getRecordComponents();
        check(reportFields.length == 1 && reportFields[0].getGenericType() instanceof ParameterizedType list
                && list.getRawType() == List.class && Arrays.equals(list.getActualTypeArguments(), new Class<?>[]{ Code.class }),
                "REPORT_FIELDS");

        for (int valid : new int[]{ -1, 1, 3600 }) {
            check(intent(Propagation.REQUIRED, false, Isolation.DEFAULT, valid).requestedTimeoutSeconds() == valid,
                    "TIMEOUT_VALID");
        }
        for (int invalid : new int[]{ Integer.MIN_VALUE, -2, 0, 3601, Integer.MAX_VALUE }) {
            IllegalArgumentException failure = expect(IllegalArgumentException.class,
                    () -> intent(Propagation.REQUIRED, false, Isolation.DEFAULT, invalid));
            check("Invalid transaction timeout".equals(failure.getMessage()), "TIMEOUT_REJECTION_MESSAGE");
        }
        expect(NullPointerException.class, () -> intent(null, false, Isolation.DEFAULT, -1));
        expect(NullPointerException.class, () -> intent(Propagation.REQUIRED, false, null, -1));
        expect(NullPointerException.class, () -> new Intent(
                true, false, false, Propagation.REQUIRED, false, Isolation.DEFAULT, -1, null, false));
        expect(NullPointerException.class, () -> new Snapshot(
                true, true, true, false, false, null, Timeout.NONE, Rollback.CLEAR));
        expect(NullPointerException.class, () -> new Snapshot(
                true, true, true, false, false, Isolation.DEFAULT, null, Rollback.CLEAR));
        expect(NullPointerException.class, () -> new Snapshot(
                true, true, true, false, false, Isolation.DEFAULT, Timeout.NONE, null));
        expect(NullPointerException.class, () -> TransactionGuard.assess(null, ACTIVE));
        expect(NullPointerException.class, () -> TransactionGuard.assess(
                intent(Propagation.REQUIRED, false, Isolation.DEFAULT, -1), null));
    }

    private static void transactionState() {
        Intent required = intent(Propagation.REQUIRED, false, Isolation.DEFAULT, -1);
        diagnose(required, ACTIVE, Code.TRANSACTION_OWNERSHIP_UNVERIFIED);
        diagnose(required, INACTIVE, Code.NO_ACTUAL_TRANSACTION, Code.RESOURCE_NOT_BOUND);
        diagnose(required, new Snapshot(false, true, true, false, false,
                Isolation.UNKNOWN, Timeout.NONE, Rollback.UNKNOWN),
                Code.NO_ACTUAL_TRANSACTION, Code.SYNCHRONIZATION_WITHOUT_TRANSACTION);
        diagnose(required, new Snapshot(true, true, false, false, false,
                Isolation.READ_COMMITTED, Timeout.NONE, Rollback.CLEAR),
                Code.RESOURCE_NOT_BOUND, Code.TRANSACTION_OWNERSHIP_UNVERIFIED);

        Intent optional = new Intent(false, false, false, Propagation.SUPPORTS,
                false, Isolation.DEFAULT, -1, Outcome.NONE, false);
        diagnose(optional, INACTIVE);
        diagnose(optional, ACTIVE, Code.TRANSACTION_OWNERSHIP_UNVERIFIED);

        Snapshot readOnly = new Snapshot(true, true, true, false, true,
                Isolation.READ_COMMITTED, Timeout.NONE, Rollback.CLEAR);
        diagnose(required, readOnly, Code.TRANSACTION_OWNERSHIP_UNVERIFIED);
        Intent write = new Intent(true, true, false, Propagation.REQUIRED,
                false, Isolation.DEFAULT, -1, Outcome.NONE, false);
        diagnose(write, readOnly, Code.READ_ONLY_WRITE, Code.TRANSACTION_OWNERSHIP_UNVERIFIED);

        diagnose(required, new Snapshot(true, true, true, false, false,
                Isolation.READ_COMMITTED, Timeout.NONE, Rollback.MARKED),
                Code.ROLLBACK_ONLY, Code.TRANSACTION_OWNERSHIP_UNVERIFIED);
        diagnose(required, new Snapshot(true, true, true, false, false,
                Isolation.READ_COMMITTED, Timeout.NONE, Rollback.UNKNOWN),
                Code.ROLLBACK_UNVERIFIED, Code.TRANSACTION_OWNERSHIP_UNVERIFIED);

        Intent jpa = new Intent(true, false, true, Propagation.REQUIRED,
                false, Isolation.DEFAULT, -1, Outcome.NONE, false);
        diagnose(jpa, ACTIVE, Code.ENTITY_MANAGER_NOT_BOUND, Code.MIXED_ACCESS_REQUIRES_EXPLICIT_FLUSH,
                Code.MIXED_ACCESS_REQUIRES_CACHE_REFRESH, Code.TRANSACTION_OWNERSHIP_UNVERIFIED);
        diagnose(jpa, new Snapshot(true, true, true, true, false,
                Isolation.READ_COMMITTED, Timeout.NONE, Rollback.CLEAR), Code.MIXED_ACCESS_REQUIRES_EXPLICIT_FLUSH,
                Code.MIXED_ACCESS_REQUIRES_CACHE_REFRESH, Code.TRANSACTION_OWNERSHIP_UNVERIFIED);
    }

    private static void isolation() {
        for (Isolation level : List.of(Isolation.READ_UNCOMMITTED, Isolation.READ_COMMITTED,
                Isolation.REPEATABLE_READ, Isolation.SERIALIZABLE)) {
            Intent intent = intent(Propagation.REQUIRED, false, level, -1);
            diagnose(intent, new Snapshot(true, true, true, false, false, level, Timeout.NONE, Rollback.CLEAR),
                    Code.TRANSACTION_OWNERSHIP_UNVERIFIED);
        }
        Intent serializable = intent(Propagation.REQUIRED, false, Isolation.SERIALIZABLE, -1);
        diagnose(serializable, ACTIVE, Code.ISOLATION_MISMATCH, Code.TRANSACTION_OWNERSHIP_UNVERIFIED);
        for (Isolation unknown : List.of(Isolation.UNKNOWN, Isolation.DEFAULT)) {
            diagnose(serializable, new Snapshot(true, true, true, false, false, unknown, Timeout.NONE, Rollback.CLEAR),
                    Code.ISOLATION_UNVERIFIED, Code.TRANSACTION_OWNERSHIP_UNVERIFIED);
        }
        diagnose(serializable, INACTIVE, Code.NO_ACTUAL_TRANSACTION, Code.RESOURCE_NOT_BOUND);
        diagnose(intent(Propagation.REQUIRED, false, Isolation.UNKNOWN, -1), ACTIVE,
                Code.TRANSACTION_OWNERSHIP_UNVERIFIED);
    }

    private static void propagation() {
        for (Propagation joining : List.of(Propagation.REQUIRED, Propagation.SUPPORTS, Propagation.MANDATORY)) {
            Snapshot deadline = new Snapshot(true, true, true, false, false,
                    Isolation.READ_COMMITTED, Timeout.ACTIVE, Rollback.CLEAR);
            diagnose(intent(joining, true, Isolation.DEFAULT, 30), deadline,
                    Code.PARTICIPATING_TIMEOUT_NOT_APPLIED, Code.TRANSACTION_OWNERSHIP_UNVERIFIED);
            diagnose(intent(joining, false, Isolation.DEFAULT, 30), deadline, Code.TRANSACTION_OWNERSHIP_UNVERIFIED);
        }
        diagnose(intent(Propagation.REQUIRES_NEW, true, Isolation.DEFAULT, -1), ACTIVE,
                Code.REQUIRES_NEW_INDEPENDENT_COMMIT, Code.TRANSACTION_OWNERSHIP_UNVERIFIED);
        diagnose(intent(Propagation.REQUIRES_NEW, false, Isolation.DEFAULT, -1), ACTIVE,
                Code.TRANSACTION_OWNERSHIP_UNVERIFIED);
        diagnose(intent(Propagation.NESTED, true, Isolation.DEFAULT, -1), ACTIVE,
                Code.TRANSACTION_OWNERSHIP_UNVERIFIED);
        diagnose(new Intent(true, false, true, Propagation.NESTED, true, Isolation.DEFAULT, -1, Outcome.NONE, false),
                new Snapshot(true, true, true, true, false, Isolation.READ_COMMITTED, Timeout.NONE, Rollback.CLEAR),
                Code.NESTED_JPA_UNSUPPORTED, Code.MIXED_ACCESS_REQUIRES_EXPLICIT_FLUSH,
                Code.MIXED_ACCESS_REQUIRES_CACHE_REFRESH, Code.TRANSACTION_OWNERSHIP_UNVERIFIED);
        diagnose(new Intent(false, false, false, Propagation.MANDATORY,
                false, Isolation.DEFAULT, -1, Outcome.NONE, false), INACTIVE, Code.NO_ACTUAL_TRANSACTION);
        for (Propagation prohibiting : List.of(Propagation.NEVER, Propagation.NOT_SUPPORTED)) {
            Intent optional = new Intent(false, false, false, prohibiting,
                    true, Isolation.DEFAULT, -1, Outcome.NONE, false);
            diagnose(optional, ACTIVE, Code.UNEXPECTED_TRANSACTION, Code.TRANSACTION_OWNERSHIP_UNVERIFIED);
            diagnose(optional, INACTIVE);
        }
    }

    private static void timeoutAndOutcome() {
        Intent request = intent(Propagation.REQUIRED, false, Isolation.DEFAULT, 30);
        diagnose(request, ACTIVE, Code.TIMEOUT_UNVERIFIED, Code.TRANSACTION_OWNERSHIP_UNVERIFIED);
        diagnose(request, new Snapshot(true, true, true, false, false,
                Isolation.READ_COMMITTED, Timeout.UNKNOWN, Rollback.CLEAR),
                Code.TIMEOUT_UNVERIFIED, Code.TRANSACTION_OWNERSHIP_UNVERIFIED);
        Snapshot expired = new Snapshot(true, true, true, false, false,
                Isolation.READ_COMMITTED, Timeout.EXPIRED, Rollback.CLEAR);
        diagnose(request, expired, Code.TIMEOUT_EXPIRED, Code.TRANSACTION_OWNERSHIP_UNVERIFIED);
        for (Outcome confirmed : List.of(Outcome.CONFIRMED_COMMIT, Outcome.CONFIRMED_ROLLBACK)) {
            Intent retry = new Intent(true, false, false, Propagation.REQUIRED,
                    false, Isolation.DEFAULT, -1, confirmed, true);
            diagnose(retry, ACTIVE, Code.TRANSACTION_OWNERSHIP_UNVERIFIED);
            diagnose(retry, expired, Code.TIMEOUT_EXPIRED, Code.TRANSACTION_OWNERSHIP_UNVERIFIED);
        }
        for (boolean retryRequested : new boolean[]{ false, true }) {
            Intent unknown = new Intent(true, false, false, Propagation.REQUIRED,
                    false, Isolation.DEFAULT, -1, Outcome.UNKNOWN, retryRequested);
            diagnose(unknown, ACTIVE, Code.OUTCOME_UNKNOWN_NO_RETRY, Code.TRANSACTION_OWNERSHIP_UNVERIFIED);
            diagnose(unknown, expired, Code.TIMEOUT_EXPIRED, Code.OUTCOME_UNKNOWN_NO_RETRY,
                    Code.TRANSACTION_OWNERSHIP_UNVERIFIED);
        }
    }

    private static Intent intent(Propagation propagation, boolean outer, Isolation isolation, int timeout) {
        return new Intent(true, false, false, propagation, outer, isolation, timeout, Outcome.NONE, false);
    }

    private static List<Class<?>> componentTypes(Class<?> type) {
        return Arrays.stream(type.getRecordComponents()).<Class<?>>map(RecordComponent::getType).toList();
    }

    private static void diagnose(Intent intent, Snapshot snapshot, Code... expected) {
        check(TransactionGuard.assess(intent, snapshot).codes().equals(List.of(expected)), "DIAGNOSTIC_CODES");
    }

    private static <T extends RuntimeException> T expect(Class<T> expected, Runnable action) {
        try {
            action.run();
        } catch (RuntimeException failure) {
            check(expected.isInstance(failure), "EXCEPTION_TYPE");
            return expected.cast(failure);
        }
        throw new AssertionError("EXCEPTION_EXPECTED");
    }

    private static void check(boolean condition, String contract) {
        if (!condition) {
            throw new AssertionError(contract);
        }
        assertions++;
    }
}
