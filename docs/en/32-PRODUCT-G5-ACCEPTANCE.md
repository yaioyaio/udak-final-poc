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

The diagnostic total p95 was 971,959 ns for plain and 1,294,000 ns for Observe. Fingerprint/ID computation was the largest mean contributor across all pairs. JDBC delegation was the largest contributor among the five slowest Observe calls. JDBC duration combines driver, network and server time. Remaining time includes framework and instrumentation overhead. Subtracting fingerprint and event times from each Observe sample yields a diagnostic p95 of 1,111,666 ns, or 14.3738% above plain. This arithmetic estimate informs profiling priorities. The G5 performance assessment at the time used the `OBSERVE-V2` measurements. [OBSERVE-V2 measurements](../../evidence/PRODUCT-G5-PERFORMANCE-OBSERVE-V2-RESULT.json)

## Prepared statement reuse and the PostgreSQL execute tail (RELEASE-017)

After a driver successfully prepares a statement, UDAK retains only the derived observation metadata on its wrapper. Each execution attempt still emits a fresh event with the original query ID, fingerprint, kind and status. Across preparations, each observer retains one private HMAC tag and its metadata for ASCII input up to 1,024 characters. Other inputs use statement-local metadata. UDAK passes binds directly to the driver and keeps neither SQL text nor bind values for reuse.

Core smoke, 247 Observe assertions, 256 adapter assertions and 10 H2 mixed-access cases passed. The checks cover event metadata equality, fresh delivery per attempt, statement and bind delegation, failure isolation and retained fields on the wrapper. [Functional evidence](../../evidence/PRODUCT-G5-OBSERVE-REUSE-CANDIDATE.json)

In the 96 archived PostgreSQL pairs, the median Observe−plain difference for `executeQuery` was −7.937 µs. In the five slowest Observe calls, the mean matched difference was +361.250 µs, or 36.32% of the total increase across those pairs. Across the other 91 pairs the mean was −12.842 µs. One of the five slowest calls spent 10.041 µs less time in `executeQuery` even though its total was 713.751 µs longer. Both arms used the same physical loopback connection and checked the same single-row result. This rules out per-sample connection establishment, pool waits and a remote network path in this fixture. [Archived PostgreSQL samples](../../evidence/PRODUCT-G5-POSTGRESQL-ATTRIBUTION.json)

A source review of pgJDBC 42.7.14 places query dispatch, stream flush and response handling in the same driver interval. The saved per-call measurements give no separate durations for these stages or the PostgreSQL backend. Run `python3 -B tools/release-performance/run-postgres-attribution.py --verify` to reproduce the numbers from the locally archived commit `940acaef` without starting a database. [Pinned pgJDBC source](https://github.com/pgjdbc/pgjdbc/blob/REL42.7.14/pgjdbc/src/main/java/org/postgresql/core/v3/QueryExecutorImpl.java)

A further interval diagnostic can correlate client-thread CPU, local socket read/write durations and server protocol phase durations by matched call. Socket wait can overlap backend work and scheduling, so report overlapping durations and leave pure transport latency unassigned unless endpoint timings establish it. Use an owned fixture and bounded metadata-only capture. Keep statement text, parameter values and raw logs out of the evidence. PostgreSQL separately times Parse, Bind and Execute on the extended protocol. [PostgreSQL 17 duration logging](https://www.postgresql.org/docs/17/runtime-config-logging.html)

On 2026-11-19, the single approved `OBSERVE-REUSE` run used the existing uninstrumented fixture, DB/driver versions, workload, limits and 5% criterion. The workload protocol and cleanup passed. Each profile completed 208 queries, verified 208 returned rows and emitted 104 Observe events with zero errors. Each arm contributed 96 measured samples. The run took 64.735 seconds. Both native fixture servers stopped, their process groups exited and cleanup reclaimed a workspace containing 1,163 files (155,668,236 bytes). The run started zero containers. [Run approval](../../evidence/PRODUCT-G5-PERFORMANCE-OBSERVE-REUSE-APPROVAL.json) · [Measured results](../../evidence/PRODUCT-G5-PERFORMANCE-OBSERVE-REUSE-RESULT.json)

| DB / driver | Baseline p95 (ns) | Observe p95 (ns) | Increase | NFR-02 |
|---|---:|---:|---:|---|
| PostgreSQL 17.11 / JDBC 42.7.14 | 1,326,417 | 1,342,792 | +1.2345% | PASS |
| MySQL 8.0.46 / Connector/J 26.10.0 | 2,757,167 | 3,467,750 | +25.7722% | FAIL |

The comparison fails NFR-02 because both profiles must pass. RELEASE-017 remains incomplete. The one-run approval has been consumed. A further performance run requires new authorization.

## MySQL latency diagnostic (RELEASE-018)

The single approved `MYSQL-ATTRIBUTION` run used native loopback MySQL 8.0.46 and Connector/J 26.10.0, with one query in flight, at most eight starts per second, and a 300-second wall limit. It verified 208 returned rows and 104 Observe events with zero errors. The run took 36.770 seconds. The server and client process groups exited, cleanup reclaimed 196 files (115,092,978 bytes), and zero containers started. The offline verifier reproduced the interval accounting from timing and count metadata. [Diagnostic approval](../../evidence/PRODUCT-G5-MYSQL-ATTRIBUTION-APPROVAL.json) · [Diagnostic evidence](../../evidence/PRODUCT-G5-MYSQL-ATTRIBUTION.json)

The diagnostic total p95 was 2,537,625 ns for plain and 2,825,292 ns for Observe (+11.3361%). Both paths used the same JDBC timers. The table compares matched Observe−plain durations.

| Interval | Mean across 96 pairs (µs) | Mean across the five slowest Observe calls (µs) |
|---|---:|---:|
| HMAC including encoding and clearing | +122.676 | +272.217 |
| JDBC delegation | −22.107 | +1,084.491 |
| Event creation and delivery | +9.311 | +21.200 |

The cache recorded 103 hits and one miss, with zero fingerprint computations during measured Observe calls. Subtracting HMAC time from each Observe sample yields an arithmetic p95 of 2,470,667 ns (−2.6386% relative to plain). This estimate guides the investigation. JDBC delegation combines driver, network and server time, and their individual contributions remain unknown.

The observer retains an initialized HMAC prototype per key. Only the request-local clone receives SQL bytes. The fallback initializes one instance per request when the provider lacks cloning. Core smoke, 253 Observe assertions, 256 adapter assertions and 10 H2 cases passed, including the fallback contract. [Functional evidence](../../evidence/PRODUCT-G5-OBSERVE-REUSE-V2-CANDIDATE.json)

## Formal Observe comparison (OBSERVE-REUSE-V2)

On 2026-11-19, the single approved `OBSERVE-REUSE-V2` run used the uninstrumented fixture with the same workload, limits and 5% criterion. The workload protocol and cleanup passed. Each profile completed 208 queries, verified 208 returned rows and emitted 104 Observe events with zero errors. Each arm contributed 96 measured samples. The run took 82.495 seconds. Both native fixture servers and their process groups exited. Cleanup reclaimed 1,164 files (155,669,513 bytes) with no scratch data remaining. Zero containers started. [Run approval](../../evidence/PRODUCT-G5-PERFORMANCE-OBSERVE-REUSE-V2-APPROVAL.json) · [Measured results](../../evidence/PRODUCT-G5-PERFORMANCE-OBSERVE-REUSE-V2-RESULT.json)

| DB / driver | Baseline p95 (ns) | Observe p95 (ns) | Increase | NFR-02 |
|---|---:|---:|---:|---|
| PostgreSQL 17.11 / JDBC 42.7.14 | 1,043,667 | 1,367,041 | +30.9844% | FAIL |
| MySQL 8.0.46 / Connector/J 26.10.0 | 1,872,125 | 2,054,875 | +9.7616% | FAIL |

Both profiles exceeded the 5% p95 limit. NFR-02 is **FAIL** and RELEASE-018 remains incomplete. The one-run approval has been consumed. A further performance run requires new authorization.

## PostgreSQL three-path crossover (RELEASE-019)

The diagnostic uses one owned PostgreSQL 17.11 instance with pgJDBC 42.7.14 and the same fixture, physical session and bind for each triplet. The plain path uses JdbcTemplate directly. The prior Observe path comes from `21aeaf2` and the current path comes from `80090a1`. Each path runs eight warmup calls and sixty measured calls. Each measured block of six triplets contains every order once. The full diagnostic uses at most 204 query starts, one in-flight call, eight starts per rolling second and 300 seconds.

Both Observe paths must emit the same metadata. The timer separates JDBC preparation, execution and other JDBC calls from HMAC tag generation, fingerprint calculation, event creation, event delivery and wrapper allocation. The remaining interval includes framework and probe overhead. The paired diagnostic informs the choice of a code change. The uninstrumented two-profile NFR-02 comparison requires a fresh approval.

On 2026-11-19, the approved diagnostic and offline verification passed. The PostgreSQL server and client process groups exited after the 33.353-second run, and cleanup reclaimed 1,027 files (52,978,867 bytes). Zero containers started. The run completed all 204 queries with zero errors and verified matching results. Each Observe path emitted 68 matching events and recorded 67 cache hits and one miss on its first warmup call.

| Path | Measured samples | Diagnostic total p95 (ns) |
|---|---:|---:|
| Plain | 60 | 1,374,083 |
| Prior Observe | 60 | 1,622,667 |
| Current Observe | 60 | 1,527,958 |

Across the 60 matched triplets, current minus prior averaged −11.553 µs total, −70.822 µs for HMAC and +52.227 µs for JDBC execution. For the three slowest current calls, current minus plain averaged +1,409.180 µs total, including +905.417 µs for JDBC execution, −85.264 µs for JDBC preparation, +84.430 µs for HMAC and +319.457 µs for the remaining interval. [Diagnostic approval](../../evidence/PRODUCT-G5-POSTGRESQL-CROSSOVER-APPROVAL.json) · [Diagnostic evidence](../../evidence/PRODUCT-G5-POSTGRESQL-CROSSOVER.json)

The three slowest current calls all ran second in their triplets. The 57th-ranked current sample defines its p95. In that triplet, JDBC execution was 558.250 µs greater than plain, the largest measured increase. The positional pattern is a lead for further diagnosis.

The HMAC reduction supports retaining the current implementation. Further attribution needs to resolve driver work, local socket waits, server processing and scheduling before selecting another code change. The proposed `OBSERVE-REUSE-V2-RECHECK` binds the existing candidate and requires fresh approval for an uninstrumented comparison on PostgreSQL and MySQL. The official OBSERVE-REUSE-V2 NFR-02 verdict remains **FAIL**, and product G5 remains **BLOCKED**.

## PostgreSQL executeQuery interval detail (RELEASE-020)

One owned native PostgreSQL 17.11 and pgJDBC 42.7.14 session alternates plain and current Observe queries. Six warmup pairs and 32 measured pairs use the same fixture and bind per pair. The paced stream has 76 target queries and 77 statistics reads. Only the target query contributes to each latency sample.

The probe records JDBC execute wall time, calling-thread CPU and socket read/write durations, counts and bytes. Between calls the fixture reads planning/execution counter deltas from `pg_stat_statements(false)` for the identified statement and requires a single additional execution. The server and socket intervals can overlap. The evidence records counters and durations. [PostgreSQL counter reference](https://www.postgresql.org/docs/17/pgstatstatements.html) · [pgJDBC socket factory](https://jdbc.postgresql.org/documentation/use/)

The single approved run and offline verification passed. The native PostgreSQL fixture allowed one query in flight and at most eight starts per rolling second. It verified 76 returned rows and 38 Observe events with zero errors. The run took 25.659 seconds. The fixture exited, cleanup reclaimed 1,029 files (53,047,146 bytes), and zero containers started. [Diagnostic approval](../../evidence/PRODUCT-G5-POSTGRESQL-EXECUTE-DETAIL-APPROVAL.json) · [Diagnostic evidence](../../evidence/PRODUCT-G5-POSTGRESQL-EXECUTE-DETAIL.json)

Across 32 measured pairs, JDBC execute wall-clock p95 was 555,250 ns for plain and 842,208 ns for current Observe. The median paired current−plain difference was +5.542 µs. For the three longest current Observe JDBC calls, the mean paired differences were +494.278 µs for JDBC execute wall time, +207.667 µs for calling-thread CPU, +227.792 µs for socket reads, +118.319 µs for socket writes, +3.972 µs for server executor time and 0 µs for server planning. Each of the 64 measured calls recorded one socket read (48 bytes) and one write (45 bytes). Both arms recorded zero plans.

All time readings describe the same calls from different vantage points. Socket and server measurements can overlap, and the CPU, socket and server values cannot be summed to explain the JDBC wall-time difference. The server counters cover planning and executor time within the wider protocol exchange. The tails in this fixture show larger differences in the client CPU and socket measurements than in the server executor counter. The cause of those differences and the share due to transport or scheduling remain unresolved.

Across the 32 pairs, the median current−plain difference for total query wall time was +100.646 µs. Subtracting JDBC execute wall time from each arm before taking the paired differences gives a median of +97.7705 µs outside JDBC execute. The next code analysis should measure Observe wrapper and event handling separately from framework and result processing outside JDBC execute.

The dedicated SQL Server host and Oracle isolation, storage and approval prerequisites remain pending, as do the publishing destination and permissions. The uninstrumented PostgreSQL/MySQL comparison was **NOT RUN** in this diagnostic. The formal NFR-02 assessment remains **FAIL** and product G5 remains **BLOCKED**.

## Direct JDBC integer binding (RELEASE-022, OBSERVE-JDBC-DIRECT)

The Observe JDBC wrapper calls the driver's `setInt(int, int)` directly, removing reflection from the bind used by the comparison fixture. Named `CallableStatement` bindings, including a null parameter name, follow the existing delegation path. The contract tests verify that each invocation reaches the driver exactly once, propagates the original `SQLException` instance on failure, and emits no Observe event for binding.

Core smoke, 253 Observe assertions, 278 adapter assertions, and 10 mixed-access H2 scenarios passed. The guarded runner confirmed cleanup of 120 temporary files (38,002,319 bytes). [Candidate functional evidence](../../evidence/PRODUCT-G5-OBSERVE-JDBC-DIRECT-CANDIDATE.json)

The formal `OBSERVE-REUSE-V2` results are preserved. PostgreSQL (+30.9844%) and MySQL (+9.7616%) both exceeded the 5% p95 limit. The operator authorized one `OBSERVE-JDBC-DIRECT` comparison under the existing limits. The approval binds the candidate sources and criteria to this run. [One-run approval](../../evidence/PRODUCT-G5-PERFORMANCE-OBSERVE-JDBC-DIRECT-APPROVAL.json) · [Prior formal results](../../evidence/PRODUCT-G5-PERFORMANCE-OBSERVE-REUSE-V2-RESULT.json)

On 2026-11-19 a read-only check matched both installed macOS ARM64 server binaries to the existing G5 fixture digests. Memory pressure returned from level 2 to level 1 before the run and stayed at level 1 across 33 host checks. The runner used the Mac's native DB binaries and left the Parallels guests in their existing states. The authorized comparison finished in 63.766 seconds. Each DB completed and verified 208 queries and emitted 104 Observe events, with zero errors or result mismatches. Both fixture servers and their process groups stopped, and cleanup removed 1,164 files (155,669,673 bytes). [Run evidence](../../evidence/PRODUCT-G5-PERFORMANCE-OBSERVE-JDBC-DIRECT-RESULT.json)

| DB / driver | Baseline p95 (ns) | Observe p95 (ns) | Increase | NFR-02 |
|---|---:|---:|---:|---|
| PostgreSQL 17.11 / JDBC 42.7.14 | 1,300,333 | 1,553,667 | +19.4822% | FAIL |
| MySQL 8.0.46 / Connector/J 26.10.0 | 2,427,625 | 2,783,291 | +14.6508% | FAIL |

Both profiles exceeded the 5% limit and the one-run approval has been used. Baseline p95 also changed between the `OBSERVE-REUSE-V2` and `OBSERVE-JDBC-DIRECT` trials, so the effect of direct binding remains unquantified. Product G5 remains **BLOCKED**. [Current assessment](../../evidence/PRODUCT-G5-ACCEPTANCE.json)

## JDBC wrapper allocation and timeout delegation (RELEASE-023, OBSERVE-JDBC-WRAPPER)

Across 60 matched PostgreSQL comparisons in RELEASE-019, current Observe minus baseline averaged +27.010 µs for proxy creation, +10.099 µs for event creation, and +1.201 µs for delivery to the fixture sink. In RELEASE-020 the paired median difference for total query time outside JDBC execution was +97.7705 µs. That interval combines wrapper and event work with other costs, including framework and result handling. The savings from each allocation and delegation change remain unmeasured. [Crossover evidence](../../evidence/PRODUCT-G5-POSTGRESQL-CROSSOVER.json) · [Execution detail](../../evidence/PRODUCT-G5-POSTGRESQL-EXECUTE-DETAIL.json)

The candidate reuses four fixed single-interface arrays, one each for `Connection`, `Statement`, `PreparedStatement`, and `CallableStatement`. Each wrapper still receives a fresh proxy and invocation handler. The statement proxy delegates `setQueryTimeout(int)` directly to the driver. The fixture configures a three-second timeout on both paths. Spring Framework 6.2.19 applies the statement timeout through `JdbcTemplate` settings and gives a current transaction timeout priority in `DataSourceUtils`. [JdbcTemplate 6.2.19](https://docs.spring.io/spring-framework/docs/6.2.19/javadoc-api/org/springframework/jdbc/core/JdbcTemplate.html#applyStatementSettings(java.sql.Statement)) · [DataSourceUtils 6.2.19](https://docs.spring.io/spring-framework/docs/6.2.19/javadoc-api/org/springframework/jdbc/datasource/DataSourceUtils.html#applyTimeout(java.sql.Statement,javax.sql.DataSource,int))

The adapter contract checks that the timeout is forwarded once, the original `SQLException` propagates, and setting the timeout emits no event. Each observed execution attempt delivers a fresh event synchronously before driver execution. The observation data retained by a prepared wrapper or sent in an event consists solely of derived metadata. Core smoke, 253 Observe assertions, 294 adapter assertions, and 10 mixed-access H2 scenarios passed. The guarded runner confirmed cleanup of 121 temporary files (38,006,104 bytes). [Candidate functional evidence](../../evidence/PRODUCT-G5-OBSERVE-JDBC-WRAPPER-CANDIDATE.json)

`OBSERVE-JDBC-WRAPPER` started at normal host memory pressure (level 1). The monitor stopped the trial after two consecutive warning readings at level 2. The runner recorded `InterruptedError` after 8.093 seconds, consuming the one-run approval. The PostgreSQL fixture server started and stopped, and its process group exited. MySQL did not start. Automatic cleanup passed and removed 1,006 files (52,881,949 bytes). The trial started zero Docker containers and zero VMs. [One-run approval](../../evidence/PRODUCT-G5-PERFORMANCE-OBSERVE-JDBC-WRAPPER-APPROVAL.json) · [Incomplete run result](../../evidence/PRODUCT-G5-PERFORMANCE-OBSERVE-JDBC-WRAPPER-RESULT.json) · [Host stop evidence](../../evidence/PRODUCT-G5-PERFORMANCE-OBSERVE-JDBC-WRAPPER-HOST-STOP.json)

The trial produced no valid candidate p95, and the official verifier rejected the result because it lacked complete measurements for both databases. `OBSERVE-JDBC-DIRECT` remains the latest valid official result, with NFR-02 **FAIL** and product G5 **BLOCKED**. One new comparison may run after host memory pressure stabilizes at normal and the operator gives new approval. The conditional Oracle and SQL Server G5 stages require both databases to pass the p95 criterion and were **NOT RUN**. [Official assessment](../../evidence/PRODUCT-G5-ACCEPTANCE.json)

## Host readiness before official measurement (RELEASE-024)

`python3 -B tools/run-g5-performance.py --host-preflight` checks macOS memory pressure for at least 15 seconds without starting the fixture. The official runner applies the same check before preparing dependencies or compiling, then reads memory pressure again just before creating the one-run claim. Warning pressure or an unavailable reading blocks preparation or the claim. Keep the host monitor active during a measured run so a later warning can still stop the owned fixtures safely.

The actual host returned `HOST_MEMORY_PRESSURE` before any new fixture or claim. Four readiness regression tests passed, including warning after preparation and preservation of the one-run claim. Core smoke and offline checks of four historical diagnostic reports also passed. The interrupted result remains preserved, and a new official comparison is **NOT RUN**. The latest valid official result and the 5% threshold still govern product G5. [Readiness tests](../../tools/release-performance/test-g5-host-readiness.py) · [Formal run limits](../../tools/product-g5-criteria.json)

## Balanced fixture rows across execution orders (RELEASE-028)

Earlier tests used the pair index to choose both the fixture row and the order. The odd row IDs always used raw → Observe, and the even row IDs always used Observe → raw. In the retained DIRECT data, the median paired Observe minus raw time was 192.917 µs with Observe second and 60.480 µs with Observe first on PostgreSQL. The corresponding MySQL medians were 222.29 µs and 18.15 µs. These comparisons mix row ID with order and cannot estimate the effect of either factor alone.

The BALANCED fixture rotates the eight row IDs by one position after each block of eight pairs. It keeps alternating the order and checks that each row has six measured pairs in each order per database. Each pair uses the same bound value in both arms. The 8 warm-up calls and 96 measured calls per arm, workload limits and +5% nearest-rank p95 criterion are unchanged. The runner binds the revised fixture and the existing WRAPPER source to the new run. Earlier approval and result files are preserved.

The one bounded BALANCED run started on 2026-11-20. PostgreSQL completed 208 calls with 208 verified rows, 104 Observe events and zero errors. Its baseline p95 was 768,000 ns and its Observe p95 was 982,250 ns (+27.8971%, FAIL). The paired medians with Observe second and first were +98.750 µs and +108.667 µs. Meeting the +5% limit at this baseline requires reducing Observe p95 by 175,850 ns.

The monitor stopped the run during MySQL after two consecutive memory-pressure warnings. It sampled normal pressure 28 times before the warnings. Both owned servers and their process groups exited, and cleanup removed 1,165 files (155,670,470 bytes). The run took 58.728 seconds and consumed its one-run approval. MySQL has no complete p95, and the product verifier rejected the incomplete receipt. The aggregate G5 decision stays BLOCKED. [Approval](../../evidence/PRODUCT-G5-PERFORMANCE-OBSERVE-JDBC-WRAPPER-BALANCED-APPROVAL.json) · [Partial measurement](../../evidence/PRODUCT-G5-PERFORMANCE-OBSERVE-JDBC-WRAPPER-BALANCED-RESULT.json) · [Host stop](../../evidence/PRODUCT-G5-PERFORMANCE-OBSERVE-JDBC-WRAPPER-BALANCED-HOST-STOP.json)

## JDBC cache tag allocation (RELEASE-029)

Each observer now derives its HMAC-SHA-256 inner and outer pads once from a random 32-byte key. Each eligible request uses a local SHA-256 engine for the two HMAC digests. This removes the per-request `Mac` clone, its two pad copies and its lock. The implementation overwrites the inner hash with the final tag and clears the temporary SQL bytes. The shared cache retains one keyed tag and derived observation metadata. The ASCII and length boundaries, fresh synchronous events and fallback to per-statement fingerprinting remain in effect. [RFC 2104](https://www.rfc-editor.org/rfc/rfc2104.html) · [OpenJDK HmacCore clone](https://github.com/openjdk/jdk17u/blob/master/src/java.base/share/classes/com/sun/crypto/provider/HmacCore.java)

The candidate matched the RFC 4231 vector and JCA `HmacSHA256` on repeated inputs around the SHA-256 padding and block boundaries. Java 17-targeted compilation, Core smoke, 278 Observe assertions, 294 JDBC adapter assertions and ten H2 cases passed. Four archived acceptance decisions and four archived diagnostic verifiers passed. The MySQL diagnostic verifier reads its original pinned fixture to replay its evidence. New real-DB performance is **NOT RUN** and product G5 stays **BLOCKED**. [RFC 4231](https://www.rfc-editor.org/rfc/rfc4231.html) · [Candidate evidence](../../evidence/PRODUCT-G5-OBSERVE-HMAC-CANDIDATE.json)

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

Product G5 remains **BLOCKED**. The latest valid official result, `OBSERVE-JDBC-DIRECT`, exceeded the p95 limit on both PostgreSQL (+19.4822%) and MySQL (+14.6508%). SQL Server native G5 requires an isolated Intel or AMD x86-64 Linux host. The current Docker engine is ARM64, and the archived SQL Server fixture used emulation. The Oracle concurrency pilot and instance-level crash recovery remain **NOT RUN**. The assessment lists unmet requirements by profile. Formal release remains **BLOCKED**. [Microsoft platform requirements](https://learn.microsoft.com/en-us/sql/linux/install-upgrade/setup?view=sql-server-ver16) · [Evidence assessment](../../evidence/PRODUCT-G5-ACCEPTANCE.json) · [Release gate](../../evidence/PHASE6-GATE.json)

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
