# Transaction & Consistency Guard — Safety Contract

English | [한국어](../ko/06-TRANSACTION-CONSISTENCY.md)

## Absolute Limits of Guarantees

It is impossible for UDAK to prevent every transaction or time mismatch issue. It provides **diagnostics / limited execution rules / contract tests**.

## 1. Single DataSource

- For JPA + JDBC/MyBatis to participate in the same local transaction, a Spring-managed DataSource and compatible TransactionManager configuration are required.
- MyBatis must use the MyBatis-Spring-managed `SqlSession` path.
- JPA dirty checking does not make pending changes visible in the DB, so call `EntityManager.flush()` when necessary before mixing in SQL.
- After JDBC/MyBatis changes, the same Entity held by JPA may be stale; `refresh`/`clear` or a redesign of persistence boundaries is required.
- SQL execution order and flush order cannot be fully automated through configuration alone.

### Test Scenarios

1. JPA insert → flush → MyBatis read → JdbcTemplate read: same value
2. JPA insert → JdbcTemplate update → RuntimeException: both roll back
3. JDBC update → JPA cached entity read: reproduce the stale cache risk and verify the response
4. Test combinations of `REQUIRES_NEW`, `readOnly`, `timeout`, and `isolation`

## 2. Different DataSources

- A single ordinary `@Transactional` does not guarantee atomic commits across multiple DBs.
- Configurations that exceed the scope of a single local transaction receive startup diagnostics and warnings or a policy block.
- If actual atomicity is required: review JTA/XA + DB/driver compatibility.
- For microservices and asynchronous integration: Outbox + Saga + idempotency + reconciliation.
- Retry after external system failures only for idempotent operations with clearly defined boundaries.

## 3. Time Policy

- Instant represents an absolute point in time. LocalDateTime has no timezone.
- Specify JDBC/DB session timezones and DB column types as explicit contracts.
- Synchronize DB/application server clocks through operational systems such as NTP.
- Compare Date/Time results for precision (microseconds/nanoseconds), DST, and timezone conversion as well.

## 4. Timeout Policy

- Transaction timeout, query timeout, socket timeout, and connection acquisition timeout are different.
- A timeout does not guarantee that the actual server query was immediately cancelled.
- Do not retry unconditionally when the DBMS cancellation/commit state is uncertain.

## 5. Diagnostic Levels (UDAK Proposal)

| Level | Evidence |
|---|---|
| T0 | DataSource/TxManager configuration scan |
| T1 | Single DS commit/rollback tests |
| T2 | Mixed JPA+MyBatis+JDBC Flush/cache tests |
| T3 | Multi-DB failure/compensation/XA verification report (not a guarantee of immediate consistency) |

The current POC `ConsistencyGuard` implements **only detection of a multiple-DataSource list and an exception**. Automatic Spring configuration inspection and multi-DB XA/transaction management are not implemented.
