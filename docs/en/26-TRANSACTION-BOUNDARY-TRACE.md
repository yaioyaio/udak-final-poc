# Transaction boundary tracing

English | [한국어](../ko/26-TRANSACTION-BOUNDARY-TRACE.md)

Expansion Phase 2 adds explicit tracing of Spring Framework 6.2.19 local transactions. The trace correlates SQL observations from the configured JPA/Hibernate, MyBatis, and JdbcTemplate hooks with Spring transaction boundaries. See the requirements and verification plan in [16-TRACEABILITY.md](16-TRACEABILITY.md).

## Adoption

1. Create a `SpringTransactionTrace` for the configured `DataSource` and the optional `EntityManagerFactory`. Supply the trace as the observation sink via `new SqlObserver(trace)`. Use that observer in the [existing explicit Observe hooks](21-LEGACY-OBSERVE-RESULTS.md).
2. At application initialization, call `trace.registerWith(manager)` to add the listener to a supported JDBC or JPA manager. It enrolls new local transactions started by this manager. Call `trace.checkpoint()` inside a transaction to mark a point on an enrolled boundary.
3. After an application-initiated JPA flush returns successfully, call `trace.markFlushCompleted()` if you want to record its position in the event sequence.
4. Call `trace.snapshot()` after the traced work and its completion callbacks finish. The immutable snapshot contains the recorded events and the count dropped because of the capture limit, contention, or diagnostic errors.

```java
var trace = new SpringTransactionTrace(dataSource, entityManagerFactory);
trace.registerWith(transactionManager);
var observer = new SqlObserver(trace);
```

## Reading the trace

| Observation | Meaning |
|---|---|
| Attachment | `ATTACHED` records enrollment after the registered Spring manager successfully starts a new transaction. Repeated checkpoints for the same Spring boundary reuse it and do not establish the presence of a `REQUIRED` declaration. |
| SQL association | The trace matches the configured resource and the identity of its holder on the current thread. Outside-transaction, unregistered, and foreign-resource observations are distinct. Association indicates a Spring boundary correlation. SQL observed after the trace records `BEFORE_COMPLETION` is unassociated with that boundary, even if the holder is still bound. SQL success and physical connection identity require independent evidence. Associated events report manager kind `JDBC` or `JPA`. Unassociated events report `NONE`. |
| Suspension and resumption | Spring suspension and resumption callbacks bracket the outer boundary while independent work runs. An inner boundary started by a registered manager has its own ID and completion. |
| Savepoint and rollback request | The savepoint callback reports creation. The rollback callback fires before the rollback operation and records the request. Confirmation of rollback requires independent evidence. |
| Explicit flush | The marker records a successful flush reported by the caller and preserves its sequence relative to SQL observations. |
| Completion | `COMMITTED`, `ROLLED_BACK`, and `UNKNOWN` reflect the status supplied by Spring. Treat a boundary with missing completion as pending and treat a snapshot with pending boundaries or dropped events as partial. |

The trace uses Spring manager begin notifications and transaction synchronization callbacks. [TransactionExecutionListener API](https://docs.spring.io/spring-framework/docs/6.2.x/javadoc-api/org/springframework/transaction/TransactionExecutionListener.html) · [TransactionSynchronization API](https://docs.spring.io/spring-framework/docs/6.2.x/javadoc-api/org/springframework/transaction/support/TransactionSynchronization.html)

The trace is opt-in and observes existing execution on the current thread. The application and Spring retain control of SQL execution, flushing, and transaction operations. Reports omit raw SQL, bind values, transaction names, connection addresses, savepoint objects, and raw exception text. Tracing emits no debug logs.

## Verification

```bash
python3 tools/run-tx-trace.py
```

| Requirement | Verification scope | Status |
|---|---|---|
| TXTRACE-001 | Explicit registration, resource correlation, unassociated observations, capture limit and immutable metadata | PASS |
| TXTRACE-002 | Spring/H2 coverage for JPA/Hibernate, MyBatis, and JdbcTemplate, commit and rollback-only, `REQUIRES_NEW`, JDBC savepoints, flush ordering and unknown completion | PASS |
| TXTRACE-003 | Pinned dependencies, bounded runner, Core/Observe/Guard regressions, bilingual docs, success/failure cleanup and metadata evidence | PASS |

The verification scope is synchronous Spring local transactions with H2. Full Boot context and tracing against the four target DBMSs are NOT RUN for this phase. XA, asynchronous propagation, and globally enabled wrapping are outside its scope.

## Actual validation

All nine guarded stages and eight new Spring/H2 trace scenarios passed with 318 assertions. The mixed fixture associated all three access paths with one local boundary and verified MyBatis visibility before and after flush and the final committed data. The inner `REQUIRES_NEW` commit survived outer rollback. The outer JDBC transaction committed after rollback to the savepoint. The `UNKNOWN` check injected an acknowledgement failure immediately after the H2 commit to reproduce a difference between the Spring outcome and the stored data. The fixture also covered erroneous enrollment from an auxiliary holder under a foreign manager and observation on a separate thread. A `REQUIRED` query inside another completion callback reproduced misattribution before the fix and was unassociated after the fix. [Execution evidence and timeline](../../evidence/TX-TRACE-VALIDATION.json)

Ten legacy H2 cases and ten Guard H2 regression cases passed alongside the Observe, adapter, and Spring Guard contracts and Core smoke. Automatic cleanup removed 157 temporary files and 38,148,035 bytes with zero remaining. The run started zero new containers and confirmed the twelve managed databases were stopped. The bounded run compiled for Java 17. The standalone Gradle build, production load, and fresh tracing against the four target DBMSs are NOT RUN.

Expansion Phase 3 links schema changes to Phase 1 query IDs and tests, then checks affected query results and Java mappings on the relevant DBMS and driver. [Roadmap](09-WBS-ROADMAP.md#product-expansion-phases)
