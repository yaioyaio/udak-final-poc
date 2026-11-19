# Product G5 acceptance criteria

English | [한국어](../ko/32-PRODUCT-G5-ACCEPTANCE.md)

The PRD sets the p95 latency target for the Observe path with rewriting disabled at no more than 5% above the raw baseline (NFR-02, RELEASE-008). Connection pool behavior has a separate functional acceptance plan (RELEASE-009). [PRD](01-PRD.md) · [Traceability](16-TRACEABILITY.md)

## Observe performance (RELEASE-008)

Run one fixed, parameterized `SELECT` against a small, isolated fixture. Use the same pinned `JdbcTemplate`, driver, SQL, bind inputs, row mapping, fixture, and connection topology in both arms of a database profile. The raw arm invokes `JdbcTemplate` directly. The Observe arm invokes it through the Observe path with rewriting disabled. Check the returned rows against the fixture and between arms.

Alternate paired execution order between raw → Observe and Observe → raw. Complete 8 warm-up calls and 96 measured calls per arm for each database profile. Time each invocation with a monotonic clock from entry to return. Exclude fixture preparation, spacing between starts, and warm-up samples from p95. Record p95 in nanoseconds using the 92nd value in each arm’s 96 sorted measurements (nearest rank). Calculate `100 × (Observe p95 − raw p95) / raw p95` independently for each profile.

A profile passes only when both arms have all prescribed calls and measured samples, the raw p95 is positive, the unrounded increase is at most 5%, and there are zero execution errors and zero result mismatches. Missing measurements prevent a pass. Evaluate each profile separately and require both profiles to pass this scope. Record exact software versions, sample counts, p95 values, errors, mismatches, and resource and cleanup results. Scope the conclusion to the tested query, fixture, settings, and versions.

| Item | Authorized single run |
|---|---|
| Profiles | Isolated native PostgreSQL 17.11 with JDBC 42.7.14 and MySQL 8.0.46 with Connector/J 26.10.0. Run over loopback, one database at a time. |
| SQL workload | Exactly 208 workload starts per database, including warm-up. At most 1 call in flight and 8 starts in any rolling second, with at least 125 ms between starts. |
| Time and resources | At most 300 seconds total, 90 CPU seconds per process, 48 PIDs and 1 GiB aggregate RSS per DB process tree, and 768 MiB of scratch storage per DB. Limit the client JVM to 256 MiB heap and 2 active CPUs, and cap logging at 16 MiB. |
| Stop and cleanup | Check fixture database health and loopback listener ownership before the workload. Stop on an error or breached limit, retain sanitized evidence, and verify that owned processes exit and temporary files are reclaimed. |

The operator directed the measurement under the previously proposed bounds. One authorized run completed on 2026-11-19. Each profile completed and verified all 208 queries, including warm-up, and recorded 104 Observe events and zero errors. The combined run took 65.716 seconds. Both native fixture servers exited and automatic scratch cleanup passed. [Criteria](../../tools/product-g5-criteria.json) · [Approval](../../evidence/PRODUCT-G5-PERFORMANCE-APPROVAL.json) · [Measured samples](../../evidence/PRODUCT-G5-PERFORMANCE.json)

| DB / driver | Baseline p95 (ns) | Observe p95 (ns) | Increase | NFR-02 |
|---|---:|---:|---:|---|
| PostgreSQL 17.11 / JDBC 42.7.14 | 676,750 | 1,000,333 | 47.8143% | FAIL |
| MySQL 8.0.46 / Connector/J 26.10.0 | 1,719,000 | 2,188,417 | 27.3076% | FAIL |

The evidence verifier reproduced each result from the 96 measured samples per arm using the fixed thresholds, sample counts and execution order. The measured comparison covers the fixed SELECT and connection topology. Attribution of latency to individual Observe operations requires separate profiling. The authorization has been consumed. Another bounded performance run requires a new authorization and a separate evidence record. [Preparation evidence](../../evidence/PRODUCT-G5-PERFORMANCE-PREPARATION.json)

## Observe hot path candidate (RELEASE-015)

The candidate shares a SHA-256 engine within one observation, precomputes the digest domains, and reuses the last implicit query ID for a matching framework and fingerprint. The observer cache stores one derived entry and the sink receives an event on every observed attempt. Common JDBC methods dispatch directly through the existing proxies. The contract suite verified fixed hashes, database forwarding, exception identity and mixed Hibernate/MyBatis/JdbcTemplate behavior on H2. Core smoke, 215 Observe assertions, 196 adapter assertions and 10 H2 cases passed. [Functional evidence](../../evidence/PRODUCT-G5-OBSERVE-CANDIDATE.json)

With explicit authorization for one run, `--run-id OBSERVE-V2` measured the candidate under the same bounds and 5% criterion. PostgreSQL and MySQL each completed 208 queries, verified 208 returned rows, and emitted 104 Observe events with zero errors. The combined run took 64.190 seconds. Both temporary servers stopped and scratch cleanup passed. [Candidate approval](../../evidence/PRODUCT-G5-PERFORMANCE-OBSERVE-V2-APPROVAL.json) · [Candidate results](../../evidence/PRODUCT-G5-PERFORMANCE-OBSERVE-V2-RESULT.json)

| DB / driver | Baseline p95 (ns) | Observe p95 (ns) | Change | NFR-02 |
|---|---:|---:|---:|---|
| PostgreSQL 17.11 / JDBC 42.7.14 | 914,583 | 1,154,333 | +26.2141% | FAIL |
| MySQL 8.0.46 / Connector/J 26.10.0 | 2,972,625 | 2,819,708 | -5.1442% | PASS |

The assessment reproduces the verdict from 96 samples per arm and retains the original source revision and its failed measurements. Baseline p95 also varied across the two runs. Quantifying the implementation's speedup requires a controlled comparison of the revisions. The candidate used its one-run approval. Source-bound release and compatibility evidence retains its revision scope. [Original decision](../../evidence/PRODUCT-G5-OBSERVE-BASELINE.json) · [Candidate preparation](../../evidence/PRODUCT-G5-OBSERVE-PREPARATION.json)

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

Oracle Free 23.26.4.0.0 with `ojdbc17` 23.26.4.0.0 and HikariCP 6.3.3 passed two functional cases on the native Linux ARM64 image. They cover rollback and connection reset on return, reuse of the same physical session, and visibility of a subsequent commit from an independent connection. The runner reused one stopped UDAK fixture for local validation in a new schema and fixed-size tablespace. It confirmed both were removed and the same 12 containers were stopped. [Oracle ARM containers](https://www.oracle.com/database/free/) · [Oracle execution evidence](../../evidence/PRODUCT-G5-ORACLE.json)

## Oracle cancellation and recovery (RELEASE-013)

The same Oracle and driver tuple passed five checks. Explicit JDBC cancellation and a query timeout each interrupted an observed lock wait and returned ORA-01013. The runner disconnected the session holding the uncommitted fixture write. HikariCP provided a different physical session, and independent queries confirmed rollback of the interrupted write and visibility of a new commit. A one-connection loopback relay discarded a real commit acknowledgement while an independent query saw the committed row. The JDBC call failed and `TransactionGuard` denied a retry. After `SHUTDOWN IMMEDIATE` and restart on the same fixture storage, the runner verified the committed and rolled-back rows and a subsequent commit. The temporary schema, tablespace and file were removed, and all 12 retained containers returned to the stopped state. [Oracle recovery evidence](../../evidence/PRODUCT-G5-ORACLE-RECOVERY.json)

## Remaining product support

Product G5 remains **BLOCKED**. The candidate passes the MySQL p95 criterion and exceeds the PostgreSQL p95 limit. SQL Server native G5 requires an isolated Intel or AMD x86-64 Linux host. The current Docker engine is ARM64, and the archived SQL Server fixture used emulation. The Oracle concurrency pilot and instance-level crash recovery remain **NOT RUN**. The assessment lists unmet requirements by profile. Formal release remains **BLOCKED**. [Microsoft platform requirements](https://learn.microsoft.com/en-us/sql/linux/install-upgrade/setup?view=sql-server-ver16) · [Evidence assessment](../../evidence/PRODUCT-G5-ACCEPTANCE.json) · [Release gate](../../evidence/PHASE6-GATE.json)

## Isolated native provider preparation (RELEASE-014)

Run `python3 -B tools/release-provider/check-sqlserver-host.py` on the assigned test host. The read-only probe checks Linux x86-64, CPU vendor, cgroup, local Docker, available resources, and the local pinned image. The operator supplies approval and evidence that the CPU is native. On the current workstation the host check returns `HOST_LINUX_X86_64`, so native SQL Server G5 remains **NOT RUN**. [Host check evidence](../../evidence/PRODUCT-G5-SQLSERVER-HOST-CHECK.json) · [SQL Server container requirements](https://learn.microsoft.com/sql/linux/quickstart-install-connect-docker?view=sql-server-ver16)

The Oracle fixture compiled against the pinned driver. `python3 -B tools/release-provider/run-oracle-instance.py --prepare` checks the local pinned image, architecture, quota prerequisites, and stopped managed count. Its `--run` path requires explicit approval for one disposable Oracle instance, a native ARM64 engine, and a 3 GiB persistent writable-layer quota. The implementation uses Docker overlay2 on XFS with project quotas and checks that Docker accepts the limit before startup. The local engine uses overlayfs; this quota prerequisite is absent. The 12 retained containers were preserved. [Preparation evidence](../../evidence/PRODUCT-G5-ORACLE-INSTANCE-PREPARATION.json) · [Docker storage limits](https://docs.docker.com/reference/cli/docker/container/run/#set-storage-driver-options-per-container)

The proposed Oracle trial limits execution to one active database, 2 CPUs, 3 GiB RAM, 512 PIDs and 600 seconds of scheduled work. The workload opens at most 2 simultaneous transactions and starts exactly 48 operations, with at most 4 starts in a rolling second. The runner targets the new fixture for a single forced exit. Recovery checks the same database identity, a new startup, durability of a committed row, rollback of an open transaction, and a subsequent commit. New Oracle runtime evidence is pending.
