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

Run functional verification for a follow-up ID with `python3 -B tools/release-performance/verify-observe-candidate.py --run-id RUN-ID`. On success it publishes the Core, Observe, JDBC/H2 and input hash evidence once in `evidence/PRODUCT-G5-PERFORMANCE-RUN-ID-CONTRACTS.json`. The original `OBSERVE-V2` proof is preserved. `verify-product-g5.py --run-id RUN-ID` checks functional evidence from that run ID against current inputs. Missing evidence is `NOT RUN`. A different ID or different inputs are rejected.

`python3 -B tools/run-g5-performance.py --proposal RUN-ID` prints the one-run proposal for the same candidate. Prepare the guarded execution once memory pressure is normal and measure after receiving explicit one-run approval. Use the +5% criterion and resource limits above.

On 2026-11-24, `OBSERVE-G5-FOLLOWUP` passed functional verification for current `develop` candidate `c0fb9a5`. Core smoke, Java 17 target compilation, 246 Observe assertions, 213 JDBC adapter assertions, and 10 in-memory H2 checks passed. Verification checked SHA-512 for all 37 current inputs and confirmed process and workspace cleanup. Real DB starts and performance runs were both zero. Use the same run ID for official PostgreSQL and MySQL p95 after obtaining explicit one-run approval and confirming stable host resources. [Functional evidence](../../evidence/PRODUCT-G5-PERFORMANCE-OBSERVE-G5-FOLLOWUP-CONTRACTS.json)

The one-run approval for official `OBSERVE-G5-FOLLOWUP` performance acceptance was recorded on 2026-11-24. It binds the established limits and the inputs of the functionally verified candidate. All 26 preflight checks that day reported memory pressure level 2, so the official test is **NOT RUN**. The runner and databases did not start, and the one-run approval remains unused. [One-run approval](../../evidence/PRODUCT-G5-PERFORMANCE-OBSERVE-G5-FOLLOWUP-APPROVAL.json)

## PostgreSQL latency attribution (RELEASE-016)

One approved diagnostic used instrumented copies of the existing `OBSERVE-V2` fixture and Observe sources in a private build directory. Both arms used the same timer around JDBC delegation. Additional Observe timers measured SQL normalization and fingerprint/ID computation, event creation, sink delivery and proxy allocation. The run verified all 208 queries and 104 Observe events with zero errors. It retained 96 measured pairs and reclaimed the temporary PostgreSQL process and its data in 38.683 seconds. [Diagnostic approval](../../evidence/PRODUCT-G5-POSTGRESQL-ATTRIBUTION-APPROVAL.json) · [Diagnostic evidence](../../evidence/PRODUCT-G5-POSTGRESQL-ATTRIBUTION.json)

| Exclusive interval | Mean paired difference across 96 pairs (µs) | Mean paired difference for the 5 slowest Observe calls (µs) |
|---|---:|---:|
| JDBC delegation | -7.199 | +463.676 |
| SQL fingerprint and query ID | +88.639 | +187.925 |
| Event creation and sink | +9.066 | +18.875 |
| Observe proxy allocation | +23.233 | +44.850 |
| Remaining time | +37.558 | +279.181 |
| Total | +151.299 | +994.508 |

The diagnostic total p95 was 971,959 ns for plain and 1,294,000 ns for Observe. Fingerprint/ID computation was the largest mean contributor across all pairs. JDBC delegation was the largest contributor among the five slowest Observe calls. JDBC duration combines driver, network and server time. Remaining time includes framework and instrumentation overhead. Subtracting fingerprint and event times from each Observe sample yields a diagnostic p95 of 1,111,666 ns, or 14.3738% above plain. This arithmetic estimate informs profiling priorities. The original `OBSERVE-V2` run supplies the G5 verdict. [G5 assessment](../../evidence/PRODUCT-G5-ACCEPTANCE.json)

## Local Observe performance diagnostics (RELEASE-031)

Keep Core, Observe, JDBC and H2 functional checks on the normal path. On a shared development Mac, L1 is a DB-free diagnostic for one JDBC cache-hit scenario. Compare the WRAPPER and HMAC candidates in the same session using separate JVMs, with the order alternated between matched blocks. One independent block contributes one pair of per-fork aggregate values. Individual calls within a fork are from the same block.

The pilot proposal uses one active fork and one benchmark thread at a time, three matched blocks, and five one-second warmup and five one-second measurement iterations per fork. Labels remain preliminary until calibration. In particular, three independent blocks cannot produce a finite two-sided 95% sign interval. After calibration, fix the regression percentage for the next comparison. The A/A noise margin is exactly half that declared percentage, and its entire paired interval must be within the symmetric margin. Judge A/B from its own relative-change interval. Use PASS when the upper bound is within the margin, FAIL when the lower bound exceeds the margin, and INCONCLUSIVE for overlap, noise or insufficient blocks. Report the median paired change and its interval in ns/op and B/op as diagnostics. Leave the regression limit unset during calibration.

The proposed JVM settings are a 512 MiB heap and two active processors. The resource receipt uses separate actual limits for elapsed time (600 seconds), aggregate process-tree RSS (1 GiB), tree CPU time (180 seconds), maximum CPU time per process (90 seconds) and one measurement fork. The batch includes A/A and any A/B sample collection. The future launcher must observe the entire owned tree during the run and confirm cleanup. JVM settings describe the heap and JVM ergonomics. They do not establish operating-system resource use. Host load average, reported swap space and power state are calibration observations. Memory warnings or incomplete resource evidence make a started run inconclusive. These limits are a proposal for approval. The tool checks recorded evidence and has no benchmark launcher.

`python3 -B tools/release-performance/assess-local-observe.py plan` prints the proposed L1 plan and the current L2 workload from the product verifier. Mode `l1` reads JSON on stdin containing `workload_started`, `regression_limit_percent` (or null), `aa_ns_per_op`, `ab_ns_per_op`, and `ab_alloc_bytes_per_op` as arrays of two-number pairs, and `resources` with the plan's named counters plus `memory_warning_observed` and `cleanup_confirmed`. Mode `l2-progress` reads an interrupted runner receipt on stdin. It distinguishes an attempted profile with inconclusive results from a profile that did not start. It can reproduce a recorded per-profile p95 and report the median paired delta in ns while the full trial remains inconclusive. Complete trials use the official verifier.

L2 retains the existing 208 calls per DB, one in flight, at most eight starts per rolling second and 300 seconds total. Keep the official +5% nearest-rank p95 acceptance and the archived evidence. A new L2 A/A trial or a larger workload requires a separate bounded plan; no extra calls are added to the existing budget. The local diagnostic never changes the official G5 decision.

## Guarded JDBC cache-hit JMH launcher (RELEASE-032)

The bench invokes `SqlObserver.prepareJdbc` repeatedly with one fixed ASCII query. Setup verifies that the preparation handle is reused. This covers observation preparation without a DB, driver, network call or statement execution. The launcher uses nine Observe Core sources from the fixed WRAPPER and HMAC commits. Four development-only Maven JARs, their POMs and applicable notices are pinned. [JMH 1.37 POM](https://github.com/openjdk/jmh/blob/1.37/pom.xml) · [Pinned dependencies](../../tools/release-performance/jmh-dependencies.json)

Run `python3 -B tools/release-performance/run-jmh-local-observe.py --prepare` to check linkage. It compiles both fixed variants for Java 17, discovers exactly one JMH benchmark per variant and checks a functional cache hit. The verified preparation launched zero measurement workloads and zero DB servers. [Preparation evidence](../../evidence/OBSERVE-L1-JMH-PREPARATION.json)

The A/A pilot uses a fresh external JVM for each HMAC sample with JMH's internal forks disabled (`-f 0`). It starts one owned JVM at a time and emits ns/op and allocation B/op. The guard watches elapsed time, process-group RSS and CPU, macOS memory pressure and unexpected descendants. The JVM CPU limit is reduced to the remaining batch CPU budget. The final reaped child contributes measured CPU time and peak RSS. The RSS monitor samples periodically and receipt validation also checks the reaped peak. The supervisor signals only its owned group and retains scratch when it cannot establish cleanup. [JMH fork guidance](https://github.com/openjdk/jmh/blob/1.37/jmh-samples/src/main/java/org/openjdk/jmh/samples/JMHSample_12_Forking.java)

`--proposal RUN_ID` prints the fixed A/A plan and input hashes. `--run RUN_ID` requires the matching explicit one-run approval in `evidence/OBSERVE-L1-RUN_ID-APPROVAL.json` and normal host memory pressure. The one-run claim follows build and host checks. The sanitized output is accepted by the local `l1` diagnostic. The proposed three matched blocks calibrate the pilot. Timing limits and a larger independent sample for comparison are separate decisions.

### HMAC A/A pilot (RELEASE-033)

The initial read-only preflight recorded memory pressure level 2 and left the approved `HMAC-AA-01` run pending. After the Mac returned to level 1, the protected launcher verified the fixed HMAC candidate and used the one-run approval. [Approval](../../evidence/OBSERVE-L1-HMAC-AA-01-APPROVAL.json) · [Initial host preflight](../../evidence/OBSERVE-L1-HMAC-AA-01-PREFLIGHT.json)

The 2026-11-20 run is **INCONCLUSIVE**. It recorded latency and allocation for two of three planned pairs. A memory pressure warning stopped the fifth of six planned samples. The 53.851 s run used a peak RSS of 407,552,000 bytes and 49.787 s of total CPU, within the numeric limits. Every owned child and process group was reaped, 55 temporary files totaling 3,028,665 bytes were removed, and DB starts were zero. The local `l1` diagnostic reported `INCONCLUSIVE / RESOURCE_EVIDENCE`. A fresh approval and sustained normal memory pressure are required for another pilot before deciding on an A/B comparison. [Run receipt](../../evidence/OBSERVE-L1-HMAC-AA-01-RESULT.json)

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

### Current-candidate PostgreSQL and MySQL functional evidence

On 2026-11-24 the latest `develop` candidate inputs passed sequential native checks on PostgreSQL 17.11/JDBC 42.7.14 and MySQL 8.0.46/Connector/J 26.10.0.

| Scope | PostgreSQL | MySQL | Evidence |
|---|---:|---:|---|
| JDBC cancellation, timeout, and pre-commit session loss | 3 PASS | 3 PASS | [Cancellation and recovery](../../evidence/DB-RECOVERY-VALIDATION.json) |
| HikariCP reset, reuse and session replacement | 2 PASS | 2 PASS | [Pool](../../evidence/PRODUCT-G5-POOL.json) |
| Graceful restart | 1 PASS | 1 PASS | [Restart](../../evidence/PRODUCT-G5-RESTART.json) |
| Abrupt exit recovery and lost commit acknowledgement | 2 PASS | 2 PASS | [Failure recovery](../../evidence/PRODUCT-G5-FAILURE.json) |

The run passed 112 cancellation and recovery assertions, 14 offline tests, and Core smoke. Verification checked current input hashes, pinned DB binaries and JDBC versions, fixture process shutdown and workspace cleanup. The four previous reports are preserved under `evidence/archive/observe-baseline/` with the exact hashes recorded by the baseline. A new official performance measurement is **NOT RUN**.

## Oracle ARM64 pool checks (RELEASE-012)

Oracle Free 23.26.4.0.0 with `ojdbc17` 23.26.4.0.0 and HikariCP 6.3.3 passed two functional cases on the native Linux ARM64 image. They cover rollback and connection reset on return, reuse of the same physical session, and visibility of a subsequent commit from an independent connection. The runner reused one stopped UDAK fixture for local validation in a new schema and fixed-size tablespace. It confirmed both were removed and the same 12 containers were stopped. [Oracle ARM containers](https://www.oracle.com/database/free/) · [Oracle execution evidence](../../evidence/PRODUCT-G5-ORACLE.json)

## Oracle cancellation and recovery (RELEASE-013)

The same Oracle and driver tuple passed five checks. Explicit JDBC cancellation and a query timeout each interrupted an observed lock wait and returned ORA-01013. The runner disconnected the session holding the uncommitted fixture write. HikariCP provided a different physical session, and independent queries confirmed rollback of the interrupted write and visibility of a new commit. A one-connection loopback relay discarded a real commit acknowledgement while an independent query saw the committed row. The JDBC call failed and `TransactionGuard` denied a retry. After `SHUTDOWN IMMEDIATE` and restart on the same fixture storage, the runner verified the committed and rolled-back rows and a subsequent commit. The temporary schema, tablespace and file were removed, and all 12 retained containers returned to the stopped state. [Oracle recovery evidence](../../evidence/PRODUCT-G5-ORACLE-RECOVERY.json)

## Remaining product support

Product G5 remains **BLOCKED**. In the prior `OBSERVE-V2` run, MySQL passed the p95 criterion and PostgreSQL exceeded the limit. The current candidate still needs official p95 measurements. The Oracle pool and recovery proof needs a refresh against current inputs, and Oracle concurrency and instance crash recovery remain **NOT RUN**. Native SQL Server G5 requires an isolated Intel or AMD x86-64 Linux host. Formal release remains **BLOCKED**. [Prior evidence assessment](../../evidence/PRODUCT-G5-ACCEPTANCE.json) · [Release gate](../../evidence/PHASE6-GATE.json)

## Isolated native provider preparation (RELEASE-014)

### SQL Server protected runner (RELEASE-025)

The runner uses the pinned SQL Server 2022 `linux/amd64` image and `mssql-jdbc` `13.6.2.jre11` on a dedicated native Intel or AMD x86-64 Linux host. Preparation checks the host, cgroup v2, local Docker, an empty container inventory, and XFS project quotas for `overlay2`. The runner creates one disposable container without a published port. Its JDBC client enters the owned container network namespace and connects over loopback. [Microsoft platform requirements](https://learn.microsoft.com/en-us/sql/linux/containers/deploy?view=sql-server-ver16) · [Docker writable-layer limits](https://docs.docker.com/reference/cli/docker/container/run/#set-storage-driver-options-per-container)

Use `python3 -B tools/release-provider/run-sqlserver-g5.py --prepare` for the read-only provider check. `--proposal` prints the pinned inputs and bounds for operator review. Before `--run`, the operator supplies the matching one-run approval for the dedicated native host, disposable instance and cleanup, and SQL Server Developer EULA. The approval record is `evidence/PRODUCT-G5-SQLSERVER-APPROVAL.json`. The runner claims it before creating the container and verifies ownership before restart or cleanup.

The trial allows 600 seconds for one container with 2 CPUs, 4 GiB RAM, 512 PIDs and a 4 GiB writable layer. It runs 48 transactions for the concurrency check, with at most 2 in flight and 4 starts in a rolling second. The fixture checks pool reset and replacement, JDBC cancel and timeout, pre-commit disconnect, and a committed write whose acknowledgement is lost. One abrupt termination and one clean restart exercise data recovery. The runner publishes a result after the fixture receipts and cleanup are confirmed. `python3 -B tools/release-provider/verify-sqlserver-g5.py` verifies the result offline and supplies the SQL Server capability statuses to the product G5 verifier.

The pinned fixture compiled for Java 17. All 22 offline tests and Core smoke passed. The Mac returned `HOST_LINUX_X86_64` before container startup. Native SQL Server G5 is **NOT RUN**. A dedicated approved host and a recorded live result are required for support verification. [Preparation evidence](../../evidence/PRODUCT-G5-SQLSERVER-PREPARATION.json) · [Runner](../../tools/release-provider/run-sqlserver-g5.py) · [Evidence verifier](../../tools/release-provider/verify-sqlserver-g5.py)

Run `python3 -B tools/release-provider/check-sqlserver-host.py` on the assigned test host. The read-only probe checks Linux x86-64, CPU vendor, cgroup, local Docker, available resources, and the local pinned image. The operator supplies approval and evidence that the CPU is native. On the current workstation the host check returns `HOST_LINUX_X86_64`, so native SQL Server G5 remains **NOT RUN**. [Host check evidence](../../evidence/PRODUCT-G5-SQLSERVER-HOST-CHECK.json) · [SQL Server container requirements](https://learn.microsoft.com/sql/linux/quickstart-install-connect-docker?view=sql-server-ver16)

### Oracle instance test and local guest readiness (RELEASE-014, RELEASE-026)

The Oracle fixture compiled against the pinned driver. `python3 -B tools/release-provider/run-oracle-instance.py --prepare` checks the local pinned image, architecture, quota prerequisites, and stopped managed count, then compiles the fixture and records preparation evidence. Its `--run` path requires explicit approval for one disposable Oracle instance, a native ARM64 engine, and a 3 GiB persistent writable-layer quota. The implementation uses Docker overlay2 on XFS with project quotas and checks that Docker accepts the limit before startup. The Mac engine uses overlayfs, so the quota prerequisite is absent there. The 12 retained containers were preserved. [Preparation evidence](../../evidence/PRODUCT-G5-ORACLE-INSTANCE-PREPARATION.json) · [Docker storage limits](https://docs.docker.com/reference/cli/docker/container/run/#set-storage-driver-options-per-container)

From a guest-local checkout on the running Ubuntu ARM64 VM, execute `python3 -B tools/release-provider/check-oracle-guest.py` before compiling the fixture. The read-only probe checks cgroup v2, two available CPUs, 4 GiB of available guest memory and Docker capacity, and 40 GiB of workspace headroom. It checks the existing local Docker daemon for an empty container inventory and the exact pinned ARM64 image with no declared volumes. Docker's data filesystem must have at least 3 GiB free and use `overlay2` on XFS with `d_type` and an enforced project quota mount. Confirm provider dedication before the trial. The approved trial checks that Docker accepts the 3 GiB limit before startup. The probe uses local metadata only and reports `container_quota_acceptance` and `oracle_instance_g5` as `NOT RUN`. [Probe](../../tools/release-provider/check-oracle-guest.py) · [Docker overlay2 prerequisites](https://docs.docker.com/engine/storage/drivers/overlayfs-driver/#prerequisites)

On 2026-11-20 the Mac reported memory pressure level 2. The existing `Ubuntu 24.04 P5-001` VM was suspended with two ARM vCPUs, 4 GiB of assigned RAM, and one virtual disk. The assigned RAM leaves no room for the guest OS above the 4 GiB available-memory check. The VM stayed suspended and its Docker storage is unverified. When host memory pressure returns to normal, preserve the guest session, plan memory for the guest OS as well as the test, and identify storage dedicated to the Docker data root before making storage changes. Run the guest probe first, then prepare the pinned fixture on a passing guest. The actual Oracle trial is **NOT RUN**.

The proposed Oracle trial limits execution to one active database, 2 CPUs, 3 GiB RAM, 512 PIDs and 600 seconds of scheduled work. The workload opens at most 2 simultaneous transactions and starts exactly 48 operations, with at most 4 starts in a rolling second. The runner targets the new fixture for a single forced exit. Recovery checks the same database identity, a new startup, durability of a committed row, rollback of an open transaction, and a subsequent commit. New Oracle runtime evidence is pending.
