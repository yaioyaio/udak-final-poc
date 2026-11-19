# Product G5 acceptance criteria

English | [한국어](../ko/32-PRODUCT-G5-ACCEPTANCE.md)

The PRD sets the p95 latency target for the Observe path with rewriting disabled at no more than 5% above the raw baseline (NFR-02, RELEASE-008). Connection pool behavior has a separate functional acceptance plan (RELEASE-009). [PRD](01-PRD.md) · [Traceability](16-TRACEABILITY.md)

## Observe performance (RELEASE-008)

Run one fixed, parameterized `SELECT` against a small, isolated fixture. Use the same pinned `JdbcTemplate`, driver, SQL, bind inputs, row mapping, fixture, and connection topology in both arms of a database profile. The raw arm invokes `JdbcTemplate` directly. The Observe arm invokes it through the Observe path with rewriting disabled. Check the returned rows against the fixture and between arms.

Alternate paired execution order between raw → Observe and Observe → raw. Complete 8 warm-up calls and 96 measured calls per arm for each database profile. Time each invocation with a monotonic clock from entry to return. Exclude fixture preparation, spacing between starts, and warm-up samples from p95. Record p95 in nanoseconds using the 92nd value in each arm’s 96 sorted measurements (nearest rank). Calculate `100 × (Observe p95 − raw p95) / raw p95` independently for each profile.

A profile passes only when both arms have all prescribed calls and measured samples, the raw p95 is positive, the unrounded increase is at most 5%, and there are zero execution errors and zero result mismatches. Missing measurements prevent a pass. Evaluate each profile separately and require both profiles to pass this scope. Record exact software versions, sample counts, p95 values, errors, mismatches, and resource and cleanup results. Scope the conclusion to the tested query, fixture, settings, and versions.

| Item | Proposed single run |
|---|---|
| Profiles | Isolated native PostgreSQL 17.11 with JDBC 42.7.14 and MySQL 8.0.46 with Connector/J 26.10.0. Run over loopback, one database at a time. |
| SQL workload | Exactly 208 workload starts per database, including warm-up. At most 1 call in flight and 8 starts in any rolling second, with at least 125 ms between starts. |
| Time and resources | At most 300 seconds total, 90 CPU seconds per process, 48 PIDs and 1 GiB aggregate RSS per DB process tree, and 768 MiB of scratch storage per DB. Limit the client JVM to 256 MiB heap and 2 active CPUs, and cap logging at 16 MiB. |
| Stop and cleanup | Check fixture database health and loopback listener ownership before the workload. Stop on an error or breached limit, retain sanitized evidence, and verify that owned processes exit and temporary files are reclaimed. |

Execution requires explicit authorization for this plan and is **NOT RUN**. The Java measurement fixture compiled, and 3 boundary checks and 9 rejection checks on synthetic inputs passed. The runner refused execution without the new approval. The prior G5 pilot passed its 48-operation schedule per database with a different read/write workload. Its timings have no matched raw baseline for NFR-02. [Criteria](../../tools/product-g5-criteria.json) · [Preparation evidence](../../evidence/PRODUCT-G5-PERFORMANCE-PREPARATION.json) · [Pilot evidence](../../evidence/RELEASE-G5-PILOT.json)

## Connection pool behavior (RELEASE-009)

Verify the following cases in a separate bounded functional run on the same isolated database and driver pairs. Use database-reported physical session identifiers and an independent connection to verify the effects on fixture data.

| Case | Acceptance criterion |
|---|---|
| Return and reset | Modify a fixture row inside an uncommitted transaction and close the borrowed connection. Verify rollback and check that the next borrow sees the configured baseline connection state. |
| Physical reuse | Borrow again after returning a healthy connection and confirm the physical session identifier is the same. Verify that a new transaction succeeds. |
| Termination and replacement | End an owned fixture session before commit. Verify rollback from the independent connection, then check that the pool replaces the terminated session within the configured timeout. Commit a fresh transaction on the replacement and confirm its effect. Verify the interrupted operation is never replayed and the existing committed fixture state is preserved. |

HikariCP 6.3.3 passed 4 cases across the two native DBs. Closing an uncommitted borrower rolled back its writes, reset connection state, and permitted reuse. A new server session replaced a terminated session and could commit. The isolated DBs stopped and their scratch space was reclaimed. Previously recorded cancellation, timeout and pre-commit loss results remain linked to their original executions. [Pool execution](../../evidence/PRODUCT-G5-POOL.json) · [Recovery evidence](../../evidence/DB-RECOVERY-VALIDATION.json)

## Server restart recovery (RELEASE-010)

Graceful restart passed 2 cases across the same native PostgreSQL and MySQL profiles. Each fixture server exited cleanly. The runner reopened the same data directory on a new owned loopback port. It verified that committed data survived, rolled-back data was absent, and a subsequent commit was visible on an independent connection. Both fixture process groups and scratch spaces were reclaimed. [Restart execution](../../evidence/PRODUCT-G5-RESTART.json)

## Abrupt exit and lost commit acknowledgement (RELEASE-011)

The instance crash and lost acknowledgement each passed on PostgreSQL 17.11/JDBC 42.7.14 and MySQL 8.0.46/Connector/J 26.10.0. For the crash, the verifier terminated the owned server while a write transaction remained open, waited for its processes to exit, then reopened the same data directory. It found the earlier committed row, confirmed that the uncommitted row was absent, and committed a new row. For the acknowledgement test, the verifier discarded the response to a real JDBC commit on a one-connection local relay. An independent query saw the committed row while the client awaited its response. After disconnecting the client, the JDBC call failed and `TransactionGuard` rejected an automatic retry. A separate connection reconciled the write as committed once. The four cases used disposable native DBs. [Failure recovery evidence](../../evidence/PRODUCT-G5-FAILURE.json)

## Oracle ARM64 pool checks (RELEASE-012)

Oracle Free 23.26.4.0.0 with `ojdbc17` 23.26.4.0.0 and HikariCP 6.3.3 passed two functional cases on the native Linux ARM64 image. They cover rollback and connection reset on return, reuse of the same physical session, and visibility of a subsequent commit from an independent connection. The runner reused one stopped UDAK fixture for local validation in a new schema and fixed-size tablespace. It confirmed both were removed and the same 12 containers were stopped. Replacement of a terminated session, cancellation, abrupt exit recovery, and lost commit acknowledgement remain **NOT RUN** on Oracle. [Oracle ARM containers](https://www.oracle.com/database/free/) · [Oracle execution evidence](../../evidence/PRODUCT-G5-ORACLE.json)

## Remaining product support

SQL Server native G5 is **NOT RUN**. The current Docker engine is ARM64 and the archived SQL Server fixture used emulation. Native verification requires an isolated Intel or AMD x86-64 Linux host. Observe p95 still requires approval for the bounded run. Formal release remains **BLOCKED**. [Microsoft platform requirements](https://learn.microsoft.com/en-us/sql/linux/install-upgrade/setup?view=sql-server-ver16) · [Evidence assessment](../../evidence/PRODUCT-G5-ACCEPTANCE.json) · [Release gate](../../evidence/PHASE6-GATE.json)
