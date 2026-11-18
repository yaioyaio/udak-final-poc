package dev.udak.rewrite;

import dev.udak.rewrite.ApprovalHistory.Event;
import dev.udak.rewrite.ApprovalHistory.Kind;
import dev.udak.rewrite.Rewrite.Approval;
import dev.udak.rewrite.Rewrite.Check;
import dev.udak.rewrite.Rewrite.Code;
import dev.udak.rewrite.Rewrite.Denied;
import dev.udak.rewrite.Rewrite.Dialect;
import dev.udak.rewrite.Rewrite.Environment;
import dev.udak.rewrite.Rewrite.Evidence;
import dev.udak.rewrite.Rewrite.Plan;
import dev.udak.rewrite.Rewrite.Provider;
import dev.udak.rewrite.Rewrite.Registry;
import dev.udak.rewrite.Rewrite.Role;
import dev.udak.rewrite.Rewrite.Template;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.attribute.PosixFilePermissions;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.Arrays;
import java.util.EnumSet;
import java.util.List;
import java.util.Set;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import java.util.function.Function;

public final class ApprovalHistoryContractTest {
    private static final Instant NOW = Instant.parse("2026-11-19T00:00:00Z");
    private static final Clock CLOCK = Clock.fixed(NOW, ZoneOffset.UTC);
    private static final String SQL = "SELECT id FROM catalog WHERE category = ? ORDER BY id LIMIT ? OFFSET ?";
    private static final Template FIRST = new Template("approval.catalog", SQL, environment("schema-1"));
    private static final Template OTHER = new Template("approval.other", SQL, FIRST.environment());
    private static final Template NEXT = new Template(FIRST.queryId(), SQL, environment("schema-2"));
    private static final Plan PLAN = new Plan(
            "SELECT id FROM catalog WHERE category = ? ORDER BY id OFFSET ? ROWS FETCH NEXT ? ROWS ONLY",
            List.of(Role.FILTER, Role.OFFSET, Role.LIMIT), List.of("id"));
    private static final Set<Check> COMPLETE = EnumSet.allOf(Check.class);
    private static final Proof FIRST_PROOF = proof(FIRST, "proof-first", COMPLETE);
    private static final Proof NEXT_PROOF = proof(NEXT, "proof-next", COMPLETE);
    private static final Proof OTHER_PROOF = proof(OTHER, "proof-other", COMPLETE);
    private static final long WAIT_SECONDS = 5;
    private static int assertions;

    public static void main(String[] args) {
        try {
            check(args.length == 1, "scratch_argument");
            Path scratch = Path.of(args[0]);
            Path journal = scratch.resolve("core-history.bin");
            historyAndReopen(journal);
            invalidJournals(scratch, journal);
            revocationAndAdmission(scratch.resolve("core-admission.bin"));
            System.out.println("APPROVAL_HISTORY_CORE PASS");
            System.out.println("ASSERTIONS=" + assertions);
        } catch (Exception | AssertionError failure) {
            String diagnostic = failure instanceof FailedCheck check ? check.getMessage()
                    : failure.getClass().getSimpleName();
            System.out.println("APPROVAL_HISTORY_CORE FAIL");
            System.out.println("DIAGNOSTIC=" + diagnostic);
            System.exit(1);
        }
    }

    private static void historyAndReopen(Path journal) throws IOException {
        long first;
        long other;
        List<Event> closedSnapshot;
        try (ApprovalHistory history = ApprovalHistory.open(journal, CLOCK)) {
            byte[] emptyJournal = Files.readAllBytes(journal);
            denied(Code.MISSING_APPROVAL, () -> execute(history, FIRST), "missing_approval");
            check(history.history(FIRST.queryId()).isEmpty(), "empty_history");
            check(!history.revoke(FIRST.queryId(), 1), "missing_revocation");

            EnumSet<Check> incomplete = EnumSet.allOf(Check.class);
            incomplete.remove(Check.NEGATIVE);
            Proof invalid = proof(FIRST, "proof-incomplete", incomplete);
            denied(Code.EVIDENCE_INVALID, () -> approve(history, invalid), "incomplete_evidence");
            denied(Code.EVIDENCE_INVALID, () -> history.approve(FIRST_PROOF.approval(), OTHER_PROOF.evidence()),
                    "cross_query_evidence");
            check(history.history(FIRST.queryId()).isEmpty(), "invalid_approval_has_no_history");
            check(Arrays.equals(emptyJournal, Files.readAllBytes(journal)), "invalid_approval_has_no_journal_event");

            first = approve(history, FIRST_PROOF);
            other = approve(history, OTHER_PROOF);
            check(first == 1 && other == 1, "query_local_generation");
            denied(Code.INVALID_INPUT, () -> approve(history, NEXT_PROOF), "replacement_requires_revocation");
            List<Event> firstSnapshot = history.history(FIRST.queryId());
            check(firstSnapshot.size() == 1, "filtered_approval_history");
            event(firstSnapshot.get(0), 1, Kind.APPROVED, first, FIRST_PROOF);
            event(history.history(OTHER.queryId()).get(0), 2, Kind.APPROVED, other, OTHER_PROOF);
            immutable(firstSnapshot);
            check(execute(history, FIRST) == PLAN && execute(history, OTHER) == PLAN, "independent_approvals");
            check(!history.revoke(FIRST.queryId(), first + 1), "future_revocation");
            check(execute(history, FIRST) == PLAN, "future_revocation_preserves_current");
            unopened(journal, "exclusive_journal_lock");

            Registry previousRegistry = history.withRegistry(FIRST, Function.identity());
            check(history.revoke(FIRST.queryId(), first), "current_revocation");
            check(!history.revoke(FIRST.queryId(), first), "duplicate_revocation");
            denied(Code.REVOKED, () -> execute(history, FIRST), "revoked_approval");
            denied(Code.REVOKED, () -> previousRegistry.withApproved(FIRST, provider(), Function.identity()),
                    "revoked_captured_registry");
            check(execute(history, OTHER) == PLAN, "unaffected_query_after_revocation");
            closedSnapshot = history.history(FIRST.queryId());
            check(closedSnapshot.size() == 2 && firstSnapshot.size() == 1, "immutable_history_snapshot");
            event(closedSnapshot.get(1), 3, Kind.REVOKED, first, FIRST_PROOF);
        }

        try (ApprovalHistory history = ApprovalHistory.open(journal, CLOCK)) {
            check(history.history(FIRST.queryId()).equals(closedSnapshot), "durable_history_and_timestamp");
            denied(Code.REVOKED, () -> execute(history, FIRST), "durable_revocation");
            check(execute(history, OTHER) == PLAN, "durable_unaffected_approval");
            long next = approve(history, NEXT_PROOF);
            check(next == first + 1, "durable_generation_continuation");
            check(!history.revoke(NEXT.queryId(), first), "stale_revocation");
            denied(Code.MISMATCH, () -> execute(history, FIRST), "superseded_environment");
            check(execute(history, NEXT) == PLAN, "replacement_approval");
            List<Event> current = history.history(NEXT.queryId());
            check(current.size() == 3, "replacement_history");
            event(current.get(2), 4, Kind.APPROVED, next, NEXT_PROOF);
            check(history.history(OTHER.queryId()).size() == 1, "query_isolation");
        }
    }

    private static void invalidJournals(Path scratch, Path journal) throws IOException {
        byte[] original = Files.readAllBytes(journal);
        check(original.length > 2, "journal_present");
        invalidJournal(scratch.resolve("core-partial.bin"), Arrays.copyOf(original, original.length - 1),
                "partial_journal");
        byte[] corrupt = original.clone();
        corrupt[corrupt.length / 2] ^= 1;
        invalidJournal(scratch.resolve("core-corrupt.bin"), corrupt, "corrupt_journal");
    }

    private static void invalidJournal(Path journal, byte[] bytes, String label) throws IOException {
        Files.createFile(journal, PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rw-------")));
        Files.write(journal, bytes);
        unopened(journal, label);
        check(Arrays.equals(bytes, Files.readAllBytes(journal)), "invalid_journal_preserved");
    }

    private static void revocationAndAdmission(Path journal) throws Exception {
        try (ApprovalHistory history = ApprovalHistory.open(journal, CLOCK)) {
            long generation = approve(history, FIRST_PROOF);
            CountDownLatch translating = new CountDownLatch(1);
            CountDownLatch resumeTranslation = new CountDownLatch(1);
            CountDownLatch admitted = new CountDownLatch(1);
            CountDownLatch resumeAction = new CountDownLatch(1);
            Provider paused = new Provider() {
                @Override public String version() { return FIRST.environment().providerVersion(); }

                @Override public Plan translate(Template template) {
                    translating.countDown();
                    await(resumeTranslation, "translation_resume");
                    return PLAN;
                }
            };
            ExecutorService worker = Executors.newSingleThreadExecutor();
            try {
                Future<Code> decision = worker.submit(() -> {
                    try {
                        return history.withRegistry(FIRST, registry -> registry.withApproved(FIRST, paused, plan -> {
                            throw new FailedCheck("revoked_action_executed");
                        }));
                    } catch (Denied failure) {
                        return failure.code();
                    }
                });
                check(translating.await(WAIT_SECONDS, TimeUnit.SECONDS), "provider_entered_translation");
                check(history.revoke(FIRST.queryId(), generation), "revoked_during_translation");
                long fresh = approve(history, FIRST_PROOF);
                check(fresh == generation + 1, "same_tuple_gets_new_generation");
                resumeTranslation.countDown();
                check(decision.get(WAIT_SECONDS, TimeUnit.SECONDS) == Code.REVOKED, "revocation_prevents_admission");

                Future<Plan> execution = worker.submit(() -> history.withRegistry(FIRST,
                        registry -> registry.withApproved(FIRST, provider(), plan -> {
                            admitted.countDown();
                            await(resumeAction, "action_resume");
                            return plan;
                        })));
                check(admitted.await(WAIT_SECONDS, TimeUnit.SECONDS), "fresh_same_tuple_admitted");
                check(history.revoke(FIRST.queryId(), fresh), "revoked_after_admission");
                denied(Code.REVOKED, () -> execute(history, FIRST), "later_execution_denied");
                resumeAction.countDown();
                check(execution.get(WAIT_SECONDS, TimeUnit.SECONDS) == PLAN, "admitted_action_completes");
            } finally {
                resumeTranslation.countDown();
                resumeAction.countDown();
                worker.shutdownNow();
                check(worker.awaitTermination(WAIT_SECONDS, TimeUnit.SECONDS), "admission_worker_terminated");
            }
        }
    }

    private static void await(CountDownLatch latch, String label) {
        try {
            if (!latch.await(WAIT_SECONDS, TimeUnit.SECONDS)) throw new FailedCheck(label);
        } catch (InterruptedException failure) {
            Thread.currentThread().interrupt();
            throw new FailedCheck(label);
        }
    }

    private static Environment environment(String schema) {
        return new Environment(Dialect.POSTGRESQL, Dialect.ORACLE, "17", "23", "driver-1", schema,
                "provider-1", "runtime-1");
    }

    private static Proof proof(Template template, String id, Set<Check> checks) {
        String source = Rewrite.fingerprint(template.sql());
        String target = Rewrite.fingerprint(PLAN.sql());
        String mapping = Rewrite.planFingerprint(PLAN);
        String digest = Rewrite.fingerprint(id);
        Evidence evidence = new Evidence(id, digest, template.queryId(), source, template.environment(), target,
                mapping, NOW.minusSeconds(5), NOW.plusSeconds(60), checks);
        Approval approval = new Approval(template.queryId(), source, template.environment(), target, mapping, id,
                digest, NOW.plusSeconds(30));
        return new Proof(approval, evidence);
    }

    private static long approve(ApprovalHistory history, Proof proof) throws IOException {
        return history.approve(proof.approval(), proof.evidence());
    }

    private static Provider provider() {
        return new Provider() {
            @Override public String version() { return FIRST.environment().providerVersion(); }
            @Override public Plan translate(Template template) { return PLAN; }
        };
    }

    private static Plan execute(ApprovalHistory history, Template template) {
        return history.withRegistry(template, registry -> registry.withApproved(template, provider(), Function.identity()));
    }

    private static void event(Event actual, long sequence, Kind kind, long generation, Proof proof) {
        check(actual.sequence() == sequence, "event_sequence");
        check(actual.kind() == kind, "event_kind");
        check(actual.generation() == generation, "event_generation");
        check(actual.recordedAt().equals(NOW), "event_timestamp");
        check(actual.approval().equals(proof.approval()), "event_approval_tuple");
    }

    private static void unopened(Path journal, String label) throws IOException {
        try (ApprovalHistory ignored = ApprovalHistory.open(journal, CLOCK)) {
            throw new FailedCheck(label);
        } catch (IOException expected) {
            check(true, label);
        }
    }

    private static void immutable(List<Event> events) {
        try {
            events.clear();
            throw new FailedCheck("immutable_history");
        } catch (UnsupportedOperationException expected) {
            check(true, "immutable_history");
        }
    }

    private static void denied(Code code, CheckedAction action, String label) throws IOException {
        try {
            action.run();
            throw new FailedCheck(label);
        } catch (Denied failure) {
            check(failure.code() == code, label);
        }
    }

    private static void check(boolean condition, String label) {
        if (!condition) throw new FailedCheck(label);
        assertions++;
    }

    @FunctionalInterface
    private interface CheckedAction { void run() throws IOException; }

    private record Proof(Approval approval, Evidence evidence) {}

    private static final class FailedCheck extends AssertionError {
        private static final long serialVersionUID = 1L;

        FailedCheck(String label) { super(label); }
    }
}
