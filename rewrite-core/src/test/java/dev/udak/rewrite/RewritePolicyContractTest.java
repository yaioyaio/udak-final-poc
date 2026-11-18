package dev.udak.rewrite;

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

import java.time.Clock;
import java.time.Instant;
import java.time.ZoneId;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.EnumSet;
import java.util.HashMap;
import java.util.IdentityHashMap;
import java.util.List;
import java.util.Map;
import java.util.function.Consumer;
import java.util.function.Supplier;

public final class RewritePolicyContractTest {
    private static final Instant NOW = Instant.parse("2026-11-18T00:00:00Z");
    private static final Clock FIXED = Clock.fixed(NOW, ZoneOffset.UTC);
    private static final Environment ENV = new Environment(Dialect.POSTGRESQL, Dialect.ORACLE,
            "17", "23", "1.1", "s1", "p1", "j17");
    private static final Template INPUT = new Template("catalog.list",
            "SELECT id, title FROM catalog WHERE category = ? ORDER BY id LIMIT ? OFFSET ?", ENV);
    private static final List<Role> ORDER = List.of(Role.FILTER, Role.OFFSET, Role.LIMIT);
    private static final List<String> LABELS = List.of("id", "title");
    private static final Plan PLAN = new Plan(
            "SELECT id, title FROM catalog WHERE category = ? ORDER BY id OFFSET ? ROWS FETCH NEXT ? ROWS ONLY",
            ORDER, LABELS);
    private static final String SOURCE = Rewrite.fingerprint(INPUT.sql());
    private static final String TARGET = Rewrite.fingerprint(PLAN.sql());
    private static final String MAPPING = Rewrite.planFingerprint(PLAN);
    private static final String OTHER_HASH = "0".repeat(64);
    private static int assertions;

    public static void main(String[] args) {
        checksBeforeProvider();
        checksAfterTranslation();
        revocationAndTime();
        registrationAndSnapshot();
        inputsAndFingerprints();
        providerAndActionFailures();
        System.out.println("Rewrite Policy assertions: " + assertions);
    }

    private static void checksBeforeProvider() {
        Case allowed = new Case();
        check(allowed.run(allowed.registry()) == PLAN);
        check(allowed.versions == 1 && allowed.translations == 1 && allowed.actions == 1);
        before(Code.MISSING_APPROVAL, c -> c.includeApproval = false);
        before(Code.MISSING_APPROVAL, c -> c.input = new Template("catalog.other", INPUT.sql(), ENV));
        before(Code.MISMATCH, c -> c.input = new Template(INPUT.queryId(), INPUT.sql() + " ", ENV));
        before(Code.MISMATCH, c -> c.approval.source = OTHER_HASH);
        List<Environment> changed = List.of(
                new Environment(Dialect.H2, ENV.target(), "17", "23", "1.1", "s1", "p1", "j17"),
                new Environment(ENV.source(), Dialect.MYSQL, "17", "23", "1.1", "s1", "p1", "j17"),
                new Environment(ENV.target(), ENV.source(), "23", "17", "1.1", "s1", "p1", "j17"),
                new Environment(ENV.source(), ENV.target(), "18", "23", "1.1", "s1", "p1", "j17"),
                new Environment(ENV.source(), ENV.target(), "17", "24", "1.1", "s1", "p1", "j17"),
                new Environment(ENV.source(), ENV.target(), "17", "23", "1.2", "s1", "p1", "j17"),
                new Environment(ENV.source(), ENV.target(), "17", "23", "1.1", "s2", "p1", "j17"),
                new Environment(ENV.source(), ENV.target(), "17", "23", "1.1", "s1", "p2", "j17"),
                new Environment(ENV.source(), ENV.target(), "17", "23", "1.1", "s1", "p1", "j21"));
        for (Environment changedEnvironment : changed) {
            before(Code.MISMATCH, c -> c.input = new Template(INPUT.queryId(), INPUT.sql(), changedEnvironment));
            before(Code.EVIDENCE_INVALID, c -> c.evidence.environment = changedEnvironment);
        }
        before(Code.EVIDENCE_INVALID, c -> c.includeEvidence = false);
        before(Code.EVIDENCE_INVALID, c -> c.approval.evidenceId = "other-proof");
        before(Code.EVIDENCE_INVALID, c -> c.evidence.query = "catalog.other");
        before(Code.EVIDENCE_INVALID, c -> c.evidence.source = OTHER_HASH);
        before(Code.EVIDENCE_INVALID, c -> c.evidence.target = OTHER_HASH);
        before(Code.EVIDENCE_INVALID, c -> c.evidence.mapping = OTHER_HASH);
        before(Code.EVIDENCE_INVALID, c -> c.evidence.digest = OTHER_HASH);
        before(Code.EVIDENCE_INVALID, c -> c.evidence.from = NOW.plusNanos(1));
        before(Code.EVIDENCE_INVALID, c -> c.approval.until = c.evidence.until.plusNanos(1));
        for (Check omitted : Check.values()) {
            before(Code.EVIDENCE_INVALID, c -> c.evidence.checks.remove(omitted));
        }
        before(Code.EXPIRED, c -> c.approval.until = NOW);
        before(Code.EXPIRED, c -> {
            c.approval.until = NOW;
            c.evidence.until = NOW;
        });

        Case versionChanged = new Case();
        versionChanged.version = () -> "p2";
        denied(Code.MISMATCH, () -> versionChanged.run(versionChanged.registry()));
        check(versionChanged.versions == 1 && versionChanged.translations == 0 && versionChanged.actions == 0);
        Case atVerification = new Case();
        atVerification.evidence.from = NOW;
        atVerification.approval.until = NOW.plusNanos(1);
        check(atVerification.run(atVerification.registry()) == PLAN);
    }

    private static void checksAfterTranslation() {
        changedPlan(() -> null);
        changedPlan(() -> new Plan(PLAN.sql() + " ", ORDER, LABELS));
        changedPlan(() -> new Plan(INPUT.sql(), ORDER, LABELS));
        changedPlan(() -> new Plan(PLAN.sql(), List.of(Role.FILTER, Role.LIMIT, Role.OFFSET), LABELS));
        changedPlan(() -> new Plan(PLAN.sql(), ORDER, List.of("title", "id")));
        changedPlan(() -> new Plan(PLAN.sql(), ORDER, List.of("id", "name")));
    }

    private static void changedPlan(Supplier<Plan> changed) {
        Case c = new Case();
        c.translation = changed;
        denied(Code.PLAN_MISMATCH, () -> c.run(c.registry()));
        check(c.versions == 1 && c.translations == 1 && c.actions == 0);
    }

    private static void revocationAndTime() {
        Case revoked = new Case();
        Registry registry = revoked.registry();
        registry.revoke(INPUT.queryId());
        denied(Code.REVOKED, () -> revoked.run(registry));
        check(revoked.versions == 0 && revoked.translations == 0 && revoked.actions == 0);

        Case checkingVersion = new Case();
        Registry revokeOnVersion = checkingVersion.registry();
        checkingVersion.version = () -> {
            revokeOnVersion.revoke(INPUT.queryId());
            return ENV.providerVersion();
        };
        denied(Code.REVOKED, () -> checkingVersion.run(revokeOnVersion));
        check(checkingVersion.versions == 1 && checkingVersion.translations == 0 && checkingVersion.actions == 0);

        Case translating = new Case();
        Registry concurrentlyRevoked = translating.registry();
        translating.translation = () -> {
            concurrentlyRevoked.revoke(INPUT.queryId());
            return PLAN;
        };
        denied(Code.REVOKED, () -> translating.run(concurrentlyRevoked));
        check(translating.translations == 1 && translating.actions == 0);

        Case expiring = new Case();
        MutableClock mutable = new MutableClock();
        expiring.clock = mutable;
        expiring.translation = () -> {
            mutable.now = expiring.approval.until;
            return PLAN;
        };
        denied(Code.EXPIRED, () -> expiring.run(expiring.registry()));
        check(expiring.translations == 1 && expiring.actions == 0);

        Case admitted = new Case();
        Registry admittedRegistry = admitted.registry();
        check(admittedRegistry.withApproved(INPUT, admitted.provider, plan -> {
            admittedRegistry.revoke(INPUT.queryId());
            return plan;
        }) == PLAN);
        denied(Code.REVOKED, () -> admitted.run(admittedRegistry));
    }

    private static void registrationAndSnapshot() {
        Case c = new Case();
        Approval approval = c.approval.approval();
        Evidence evidence = c.evidence.evidence();
        Map<String, Approval> approvals = new HashMap<>(Map.of(INPUT.queryId(), approval));
        Map<String, Evidence> proofs = new HashMap<>(Map.of(evidence.id(), evidence));
        Registry registered = new Registry(approvals, proofs, FIXED);
        approvals.clear();
        proofs.clear();
        c.evidence.checks.clear();
        check(c.run(registered) == PLAN);
        check(evidence.passed().size() == Check.values().length);
        immutable(() -> evidence.passed().clear());

        Map<String, Approval> duplicateIds = new IdentityHashMap<>();
        duplicateIds.put(new String(approval.queryId()), approval);
        duplicateIds.put(new String(approval.queryId()), approval);
        denied(Code.INVALID_INPUT, () -> new Registry(duplicateIds, proofs, FIXED));
        Map<String, Evidence> duplicateProofs = new IdentityHashMap<>();
        duplicateProofs.put(new String(evidence.id()), evidence);
        duplicateProofs.put(new String(evidence.id()), evidence);
        denied(Code.INVALID_INPUT, () -> new Registry(approvals, duplicateProofs, FIXED));
        denied(Code.INVALID_INPUT, () -> new Registry(Map.of("wrong", approval), proofs, FIXED));
        denied(Code.INVALID_INPUT, () -> new Registry(approvals, Map.of("wrong", evidence), FIXED));
        approvals.put("null", null);
        denied(Code.INVALID_INPUT, () -> new Registry(approvals, proofs, FIXED));
        denied(Code.INVALID_INPUT, () -> new Registry(null, proofs, FIXED));
        denied(Code.INVALID_INPUT, () -> new Registry(Map.of(), null, FIXED));
        denied(Code.INVALID_INPUT, () -> new Registry(Map.of(), proofs, null));
        denied(Code.INVALID_INPUT, () -> registered.withApproved(null, c.provider, p -> p));
        denied(Code.INVALID_INPUT, () -> registered.withApproved(INPUT, null, p -> p));
        denied(Code.INVALID_INPUT, () -> registered.withApproved(INPUT, c.provider, null));
        denied(Code.INVALID_INPUT, () -> registered.revoke(null));

        List<Role> roles = new ArrayList<>(ORDER);
        List<String> columns = new ArrayList<>(LABELS);
        Plan snapshot = new Plan(PLAN.sql(), roles, columns);
        roles.clear();
        columns.clear();
        check(snapshot.equals(PLAN));
        immutable(() -> snapshot.bindOrder().clear());
        immutable(() -> snapshot.columns().clear());
        for (Object value : List.of(INPUT, ENV, approval, evidence, snapshot)) {
            check(value.toString().equals(value.getClass().getSimpleName() + "[redacted]"));
        }
    }

    private static void inputsAndFingerprints() {
        check(Rewrite.fingerprint("abc").equals("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"));
        check(!Rewrite.fingerprint("é").equals(Rewrite.fingerprint("e\u0301")));
        denied(Code.INVALID_INPUT, () -> Rewrite.fingerprint("\uD800"));
        denied(Code.INVALID_INPUT, () -> new Template("x", "", ENV));
        denied(Code.INVALID_INPUT, () -> new Template("x", "a".repeat(16_385), ENV));
        denied(Code.INVALID_INPUT, () -> new Template("a".repeat(129), "a", ENV));
        denied(Code.INVALID_INPUT, () -> new Template("bad id", "a", ENV));
        denied(Code.INVALID_INPUT, () -> new Template("x", "a", null));
        check(new Template("x".repeat(128), "a".repeat(16_384), ENV).queryId().length() == 128);
        denied(Code.INVALID_INPUT, () -> new Environment(null, ENV.target(), "1", "1", "1", "1", "1", "1"));
        for (String bad : Arrays.asList(null, "", "with space", "x".repeat(65))) {
            denied(Code.INVALID_INPUT, () -> new Environment(ENV.source(), ENV.target(), bad, "1", "1", "1", "1", "1"));
        }
        Case invalidHash = new Case();
        invalidHash.approval.source = "x".repeat(64);
        denied(Code.INVALID_INPUT, () -> invalidHash.approval.approval());
        denied(Code.INVALID_INPUT, () -> new Plan("s", ORDER, List.of()));
        denied(Code.INVALID_INPUT, () -> new Plan("s", ORDER, java.util.Collections.nCopies(33, "id")));
        denied(Code.INVALID_INPUT, () -> new Plan("s", ORDER, List.of("id DESC")));
        denied(Code.INVALID_INPUT, () -> new Plan("s", ORDER, Arrays.asList("id", null)));
        denied(Code.INVALID_INPUT, () -> new Plan("s", List.of(Role.FILTER, Role.LIMIT), LABELS));
        denied(Code.INVALID_INPUT, () -> new Plan("s", List.of(Role.FILTER, Role.LIMIT, Role.LIMIT), LABELS));
        denied(Code.INVALID_INPUT, () -> new Plan("s", Arrays.asList(Role.FILTER, null, Role.OFFSET), LABELS));
        check(!Rewrite.planFingerprint(new Plan("s", ORDER, List.of("ab", "c")))
                .equals(Rewrite.planFingerprint(new Plan("s", ORDER, List.of("a", "bc")))));
    }

    @SuppressWarnings("removal")
    private static void providerAndActionFailures() {
        Case versionFails = new Case();
        versionFails.version = () -> { throw new IllegalStateException("fixture detail"); };
        denied(Code.PROVIDER_FAILED, () -> versionFails.run(versionFails.registry()));
        check(versionFails.translations == 0 && versionFails.actions == 0);

        Case translateFails = new Case();
        translateFails.translation = () -> { throw new AssertionError("fixture detail"); };
        denied(Code.PROVIDER_FAILED, () -> translateFails.run(translateFails.registry()));
        check(translateFails.actions == 0);
        Case unsupported = new Case();
        unsupported.translation = () -> {
            Denied dirty = new Denied(Code.UNSUPPORTED);
            dirty.addSuppressed(new IllegalStateException("fixture detail"));
            throw dirty;
        };
        denied(Code.UNSUPPORTED, () -> unsupported.run(unsupported.registry()));
        check(unsupported.actions == 0);

        for (Error fatal : List.of(new InternalError(), new ThreadDeath())) {
            Case c = new Case();
            c.translation = () -> { throw fatal; };
            Throwable actual = null;
            try {
                c.run(c.registry());
            } catch (Error observed) {
                actual = observed;
            }
            check(actual == fatal && c.actions == 0);
        }
        Case c = new Case();
        RuntimeException executorFailure = new IllegalStateException("executor fixture");
        RuntimeException actual = null;
        try {
            c.registry().withApproved(INPUT, c.provider, p -> {
                c.actions++;
                throw executorFailure;
            });
        } catch (RuntimeException observed) {
            actual = observed;
        }
        check(actual == executorFailure && c.translations == 1 && c.actions == 1);
    }

    private static final class Attestation {
        String query = INPUT.queryId();
        String source = SOURCE;
        String target = TARGET;
        String mapping = MAPPING;
        String evidenceId = "test-evidence";
        String digest = "a".repeat(64);
        Environment environment = ENV;
        Instant from = NOW.minusSeconds(10);
        Instant until = NOW.plusSeconds(60);
        EnumSet<Check> checks = EnumSet.allOf(Check.class);

        Approval approval() {
            return new Approval(query, source, environment, target, mapping, evidenceId, digest, until);
        }

        Evidence evidence() {
            return new Evidence(evidenceId, digest, query, source, environment, target, mapping, from, until, checks);
        }
    }

    private static final class Case {
        final Attestation approval = new Attestation();
        final Attestation evidence = new Attestation();
        boolean includeApproval = true;
        boolean includeEvidence = true;
        Template input = INPUT;
        Clock clock = FIXED;
        Supplier<String> version = ENV::providerVersion;
        Supplier<Plan> translation = () -> PLAN;
        int versions;
        int translations;
        int actions;
        final Provider provider = new Provider() {
            public String version() { versions++; return version.get(); }
            public Plan translate(Template template) { translations++; return translation.get(); }
        };

        Registry registry() {
            Map<String, Approval> approvals = includeApproval ? Map.of(approval.query, approval.approval()) : Map.of();
            Map<String, Evidence> proofs = includeEvidence ? Map.of(evidence.evidenceId, evidence.evidence()) : Map.of();
            return new Registry(approvals, proofs, clock);
        }

        Plan run(Registry registry) {
            return registry.withApproved(input, provider, plan -> { actions++; return plan; });
        }
    }

    private static final class MutableClock extends Clock {
        Instant now = NOW;
        public ZoneId getZone() { return ZoneOffset.UTC; }
        public Clock withZone(ZoneId zone) { return Clock.fixed(now, zone); }
        public Instant instant() { return now; }
    }

    private static void before(Code code, Consumer<Case> change) {
        Case c = new Case();
        change.accept(c);
        denied(code, () -> c.run(c.registry()));
        check(c.versions == 0 && c.translations == 0 && c.actions == 0);
    }

    private static void denied(Code expected, Runnable operation) {
        try {
            operation.run();
        } catch (Denied actual) {
            check(actual.code() == expected);
            check(actual.getMessage().equals("Rewrite denied"));
            check(actual.getCause() == null && actual.getSuppressed().length == 0);
            return;
        }
        throw new AssertionError("Expected policy denial");
    }

    private static void immutable(Runnable operation) {
        try {
            operation.run();
        } catch (UnsupportedOperationException expected) {
            check(true);
            return;
        }
        throw new AssertionError("Expected immutable snapshot");
    }

    private static void check(boolean condition) {
        if (!condition) throw new AssertionError("Rewrite policy assertion " + (assertions + 1));
        assertions++;
    }
}
