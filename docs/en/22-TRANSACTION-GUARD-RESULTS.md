# Phase 4 Transaction & Consistency Guard

English | [한국어](../ko/22-TRANSACTION-GUARD-RESULTS.md)

## Scope and decision

Explicit configuration, current-thread transaction diagnostics and actual Spring/H2 local contracts passed. T-014 is complete within this scope.

Requirements: P4-CORE / P4-SPRING / P4-TX / P4-HARNESS, FR-010, T-014. `consistency-core` provides JDK-only policies and immutable enum reports, `consistency-spring` diagnoses explicit configuration/current-thread state, and `consistency-testkit` tests Spring/H2 contracts.

## Explicit wiring and enforcement

Supply the same DataSource reference and one supported local transaction manager. For JPA, supply the actual EMF; for MyBatis, supply the actual SqlSessionTemplate. Unused optional framework arguments may be null. Input lists are defensive copies, and handles are compared by reference identity. The application owns the original resources, managers and pool lifecycle.

```java
import java.util.List;
import dev.udak.consistency.TransactionGuard.*;
import dev.udak.consistency.spring.SpringConsistencyGuard;

var wiring = new SpringConsistencyGuard.Configuration(
    sharedDataSource, List.of(sharedDataSource), List.of(transactionManager),
    entityManagerFactory, sqlSessionTemplate, jdbcTemplate);
SpringConsistencyGuard.inspectConfiguration(wiring).requireAllowed();

// Inside the existing Spring transaction boundary:
var intent = new Intent(true, true, true, Propagation.REQUIRED, false,
    Isolation.DEFAULT, -1, Outcome.NONE, false);
SpringConsistencyGuard.inspectTransaction(wiring, intent).requireAllowed();
```

Inspection is explicitly invoked. `requireAllowed()` or `enforce(Mode.BLOCK)` rejects ERRORs with a fixed-message exception. `Mode.REPORT_ONLY` explicitly collects diagnostics only. Exceptions contain no original objects, SQL or exception causes. Starter discovery and configuration-property binding belong to Phase 6.

## Diagnostic meanings and limits

- Checks registered DS/manager lists, manager/EMF/MyBatis/JdbcTemplate references and SpringManagedTransactionFactory. It does not discover unprovided beans or other execution paths. Different wrappers, unknown managers and unverified EMFs are conservatively rejected.
- Snapshots read current-thread Spring metadata and identity-matching holders. ActualTx plus resource binding does not prove manager ownership, physical participation or successful commit. `TRANSACTION_OWNERSHIP_UNVERIFIED` remains a warning.
- readOnly is a Spring declaration, not a DB write-prohibition guarantee. A write intent in a readOnly scope is rejected before execution. Null isolation becomes UNKNOWN; no DB default is inferred.
- Callers declare propagation, outer-boundary presence, requested isolation/timeout, previous outcome and retry intent. Participating REQUIRED scopes may not apply a new timeout, and REQUIRES_NEW can commit independently. JPA NESTED is rejected because JDBC savepoints do not restore the persistence context as well.
- Timeout uses only holder hasTimeout/getDeadline to classify UNKNOWN/NONE/ACTIVE/EXPIRED. It does not change rollback-only through getTimeToLive accessors. Rollback reflects only matching Spring holders, not complete provider-local/JPA global state.
- An uncertain commit outcome produces the `OUTCOME_UNKNOWN_NO_RETRY` ERROR. No automatic retry after timeout/uncertain outcomes or immediate cancellation of running server queries is performed. SQL, flush, caches and transaction settings/lifecycle remain unchanged.

## Validation and reproduction

```bash
python3 tools/run-phase4.py
python3 tools/verify-phase4.py
```

| Check | Actual execution result |
| --- | --- |
| JDK-only guard policy | 123 assertions PASS |
| Spring wiring and current-thread diagnostics | 52 assertions PASS |
| New transaction contracts | 205 assertions PASS (9 actual Spring/H2 scenarios, 1 unknown-outcome policy case) |
| Legacy mixed-access H2 regression | 10 scenarios PASS |
| Existing Core, Observe and adapter regressions | 74 / 202 / 188 assertions PASS |
| Evidence verifier | 13 checks PASS (including path injection and missing-evidence cases) |

Execution, verifier and final gate evidence. [PHASE4-VALIDATION.json](../../evidence/PHASE4-VALIDATION.json), [PHASE4-VERIFIER-VALIDATION.json](../../evidence/PHASE4-VERIFIER-VALIDATION.json), [PHASE4-GATE.json](../../evidence/PHASE4-GATE.json).

The first run passed 49 Spring diagnostic assertions. Independent static review then identified nonfatal `AssertionError` details escaping inspection, incomplete prior-report path allowlisting, missing source-path checks before hashing, and incomplete per-artifact dependency evidence verification. These boundaries were strengthened and the final bounded run and verifier passed. Earlier successful execution reports are preserved in `.git/udak-phase4/previous-reports`.

New functionality is actually tested at Spring/H2 local propagation and policy boundaries. New four-vendor readOnly/isolation/timeout matrices, XA/distributed atomicity, Boot autoconfiguration/Gradle/Boot 3/4 certification, operational recovery and load/performance remain NOT RUN. Existing Phase 3 evidence for 40 scenarios across four real DBs is preserved separately, without claiming a Phase 4 rerun.

The runner reuses the 36 pinned Phase 3 dependencies with a Java 17 target, JVM heap 256 MiB, metaspace 128 MiB, 2 active CPUs, 30-second child CPU, 300-second total wall time and workspace cap of 2,000 entries/128 MiB. Owned workspace cleanup runs on success, failure and normal interruption. Original/uncertain material and all 8 existing managed databases, data and secret configuration are preserved.

Automatic cleanup after the final guarded run removed 152 workspace files (38,113,156 bytes), leaving 0 files and no workspace directory. 0 new Docker containers started. All 8 existing managed databases and their data were preserved in the stopped state.

## References and next phase

Implementation follows Spring 6.2.19 [propagation handling](https://github.com/spring-projects/spring-framework/blob/v6.2.19/spring-tx/src/main/java/org/springframework/transaction/support/AbstractPlatformTransactionManager.java), [JPA transaction boundaries](https://github.com/spring-projects/spring-framework/blob/v6.2.19/spring-orm/src/main/java/org/springframework/orm/jpa/JpaTransactionManager.java), and [MyBatis-Spring transaction contracts](https://mybatis.org/spring/transactions.html).

Next is Phase 5 verified, approved selective SQL translation. Check Query ID, exact-SQL fingerprint, environment/schema/provider versions and validation evidence together, rejecting unapproved, unsupported or mismatched inputs by default. Do not enable automatic translation without actual semantic-equivalence validation.
