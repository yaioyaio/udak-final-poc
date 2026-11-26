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

### Official performance acceptance for the current candidate

`OBSERVE-G5-FOLLOWUP` ran once on 2026-11-24 under the existing approval. Three consecutive preflight checks reported normal macOS memory pressure at level 1, and no warning was observed during the run. The run completed in 63.546 seconds.

| DB | Baseline p95 (ns) | Observe p95 (ns) | Increase | Verdict |
|---|---:|---:|---:|---|
| PostgreSQL 17.11 | 732,791 | 837,291 | +14.2605% | FAIL |
| MySQL 8.0.46 | 2,037,833 | 2,344,167 | +15.0323% | FAIL |

Independent verification checked the input hashes and reproduced p95 and the verdict from 96 samples per arm. Each DB completed 208 queries with zero result mismatches, zero errors, and 104 Observe events. Both fixture DBs and their process groups stopped, and 1,162 temporary files were removed. The one-run approval was consumed. Both profiles exceeded +5%, so the dedicated Oracle preflight remains deferred. [Execution evidence](../../evidence/PRODUCT-G5-PERFORMANCE-OBSERVE-G5-FOLLOWUP-RESULT.json)

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

### Normalized byte candidate

Across 96 pairs per DB in `OBSERVE-G5-FOLLOWUP`, the median Observe-minus-baseline difference was 102.375 µs on PostgreSQL and 119.021 µs on MySQL. Observe was slower in 81 and 62 pairs, respectively. In the earlier PostgreSQL diagnosis, the fingerprint and query ID segment averaged an additional 88.639 µs. JDBC delegation averaged an additional 463.676 µs across the five slowest Observe samples. The latest paired samples measured end-to-end latency. [Official samples](../../evidence/PRODUCT-G5-PERFORMANCE-OBSERVE-G5-FOLLOWUP-RESULT.json) · [Earlier segment diagnosis](../../evidence/PRODUCT-G5-POSTGRESQL-ATTRIBUTION.json)

The shared `SqlShape` path writes normalized ASCII tokens into a byte array and passes its used range to SHA-256. This avoids creating and re-encoding the normalized string as UTF-8. The buffer is local to the call. Verification covered existing fingerprints, observation reasons and events and the pinned hashes of the previous approval, result and contract evidence.

`OBSERVE-SHAPE-BYTES-01` passed Core smoke, Java 17 target compilation, 250 Observe assertions, 213 JDBC adapter assertions, 10 H2 checks and 22 offline checks. Verification checked 37 input hashes and cleanup. The functional run did not measure official p95. Apply the existing +5% criterion after a new one-run approval and a stable host check. [Functional evidence](../../evidence/PRODUCT-G5-PERFORMANCE-OBSERVE-SHAPE-BYTES-01-CONTRACTS.json)

The one-run approval for official `OBSERVE-SHAPE-BYTES-01` acceptance was recorded on 2026-11-25. Checks verified the 11 inputs shared with the functional proof, the pinned PostgreSQL and MySQL binaries, and the approved plan. [One-run approval](../../evidence/PRODUCT-G5-PERFORMANCE-OBSERVE-SHAPE-BYTES-01-APPROVAL.json)

Three consecutive preflight checks that day reported memory pressure level 1. The official run completed in 63.315 seconds without an observed pressure warning. The one-run approval was consumed.

| DB | Baseline p95 (ns) | Observe p95 (ns) | Increase | Verdict |
|---|---:|---:|---:|---|
| PostgreSQL 17.11 | 683,375 | 992,541 | +45.2410% | FAIL |
| MySQL 8.0.46 | 1,604,875 | 1,887,667 | +17.6208% | FAIL |

Each DB completed 208 queries with zero result mismatches, zero errors and 104 Observe events. Independent verification recomputed p95 from 96 samples per arm and confirmed shutdown of both fixture DBs and their process groups and removal of 1,162 temporary files. Both profiles exceeded the +5% limit. [Official measurement](../../evidence/PRODUCT-G5-PERFORMANCE-OBSERVE-SHAPE-BYTES-01-RESULT.json)

### PostgreSQL normalization and JDBC comparison plan

Across the two latest official PostgreSQL runs, baseline p95 moved from 732.791 to 683.375 µs, and Observe p95 moved from 837.291 to 992.541 µs. The median paired difference moved from 102.375 to 118.750 µs, and the p95 of paired differences moved from 431.709 to 598.916 µs. Earlier instrumentation found an average JDBC delegation difference of 463.676 µs in the five slowest Observe samples, including 361.250 µs in `executeQuery`. Its fingerprint segment combined normalization, hashing and query ID. The latest official samples have end-to-end timings. [Previous official samples](../../evidence/PRODUCT-G5-PERFORMANCE-OBSERVE-G5-FOLLOWUP-RESULT.json) · [Normalized-byte official samples](../../evidence/PRODUCT-G5-PERFORMANCE-OBSERVE-SHAPE-BYTES-01-RESULT.json) · [Historical segments](../../evidence/PRODUCT-G5-POSTGRESQL-ATTRIBUTION.json)

Compare `4eb8f40` and `8038c2d` using the same PostgreSQL 17.11 instance, JDBC 42.7.14, JDK, SELECT and eight row inputs. Run before, after, after, before in four blocks. Each block pairs baseline and Observe with four warmup pairs and sixteen measured pairs, for 160 query starts. Each row is measured once in each starting order per block. The proposed limits are one in-flight query, at most eight starts per rolling second, minimum spacing 125 ms, total 300 seconds and the existing resource limits.

Time normalization token generation separately from hashing and query ID. Use identical instrumentation for JDBC prepare, executeQuery and other delegation on each arm. Record event creation and delivery, proxy and residual time separately. Compare the paired median, starting orders and segments in the slowest samples. Verify returned rows, events, segment totals, process shutdown and cleanup. Use the diagnostic result to select a change.

The read-only command `python3 -B tools/release-performance/assess-local-observe.py postgres-comparison-plan` recomputes the saved samples and historical segment totals and prints the unsigned plan. Both revisions compiled for Java 17 and each passed 250 assertions from the same Observe contract. Core smoke, 24 offline tests and cleanup passed.

Run `python3 -B tools/release-performance/run-postgres-comparison.py prepare` to verify the pinned sources and PostgreSQL binary and compile the temporary instrumented variants for Java 17. The generated instrumentation retains the current observation reason callback. Each block uses a fresh JVM and shares one physical connection between both arms. All four blocks share the database and fixture. The parent enforces and verifies an additional 125 ms lower bound across block boundaries. The runner checks host memory pressure before launch and while monitoring owned processes.

Guarded preparation passed. Fourteen new offline checks covered timing totals, query order, event agreement, approval denial, and synthetic process reaping. The runner checks one-run approval for the hash emitted by `proposal` before executing `run` with the same input hashes. The `verify` mode recomputes segment totals, medians by starting arm, segment deltas for the two slowest Observe pairs per block, and validates cleanup evidence. The diagnostic leaves the official PostgreSQL and MySQL G5 outcome unchanged.

On 2026-11-25, the single approved launch of `POSTGRES-OBSERVE-ABBA-01` started at host memory pressure level 1. Pressure rose to level 2 during the first block and the guard stopped it with `HOST_MEMORY_PRESSURE`. Zero of four blocks completed, and the diagnostic was **INCONCLUSIVE**. The isolated PostgreSQL instance and its owned process group stopped, and cleanup removed 1,052 temporary files. The result verifier rejected a diagnostic PASS for the incomplete evidence. The run yielded no segment samples for selecting a product change. [One-run approval](../../evidence/PRODUCT-G5-POSTGRES-OBSERVE-ABBA-01-APPROVAL.json) · [Interrupted run evidence](../../evidence/PRODUCT-G5-POSTGRES-OBSERVE-ABBA-01-RESULT.json)

Confirm a stable test environment, prepare a separate diagnostic ID, and record new one-run approval before repeating the comparison. Use a valid diagnosis to select a change, verify the candidate, and get fresh approval for a new official PostgreSQL and MySQL acceptance ID. Official two-DB acceptance is **NOT RUN**.
### PostgreSQL diagnosis after stability checks

The single run of `POSTGRES-OBSERVE-ABBA-02` confirmed memory pressure level 1 at seven samples five seconds apart and retained the same execution limits. All four blocks passed, verifying 160 queries and rows, 80 events and 64 measured pairs. The lower bound on start spacing was 125.051584 ms and the conservative rolling maximum was eight starts per second. The process groups exited and cleanup removed 1,055 temporary files. The verifier reproduced the segment summaries. [Retry approval](../../evidence/PRODUCT-G5-POSTGRES-OBSERVE-ABBA-02-APPROVAL.json) · [Verified samples](../../evidence/PRODUCT-G5-POSTGRES-OBSERVE-ABBA-02-RESULT.json)

The block medians for paired Observe-minus-plain time ranged from 37.0 to 78.1 µs for fingerprint and ID, and 25.0 to 37.7 µs for normalization. The JDBC execution median ranged from −48.2 to +48.2 µs. For the two slowest Observe pairs per block, mean JDBC execution deltas ranged from +148.1 to +214.0 µs. Prioritize the repeated fingerprint and ID cost. Instrumentation cannot separate JDBC time into server, driver and host contributions or resolve a latency ranking between revisions. Official two-DB acceptance follows candidate functional verification under a new test ID.

### SHA-256 initialization candidate

`OBSERVE-DIGEST-TEMPLATE-01` creates an independent digest for each call by cloning a pristine SHA-256 prototype. Providers without clone support construct a new digest. The tests checked golden fingerprints and query IDs and isolated the digest instances. Java 17 target compilation, Core smoke, 253 Observe assertions, 213 JDBC adapter assertions, 10 H2 compatibility checks and cleanup passed. The official approval for this ID matched all 11 inputs shared with the functional evidence. [Functional evidence](../../evidence/PRODUCT-G5-PERFORMANCE-OBSERVE-DIGEST-TEMPLATE-01-CONTRACTS.json) · [Official one-run approval](../../evidence/PRODUCT-G5-PERFORMANCE-OBSERVE-DIGEST-TEMPLATE-01-APPROVAL.json)

On 2026-11-25, the approved official trial ran once after seven level-1 memory pressure readings five seconds apart. Each DB completed 208 queries and row checks, with zero errors or mismatches and 104 events. The verifier recalculated p95 from 96 samples per arm. Both fixture DBs and their process groups stopped, and cleanup removed 1,162 temporary files. [Official measurement evidence](../../evidence/PRODUCT-G5-PERFORMANCE-OBSERVE-DIGEST-TEMPLATE-01-RESULT.json)

| Profile | Baseline p95 (µs) | Observe p95 (µs) | Change | NFR-02 |
|---|---:|---:|---:|---|
| PostgreSQL | 439.250 | 592.416 | +34.8699% | FAIL |
| MySQL | 1119.959 | 1053.875 | −5.9006% | PASS |

For PostgreSQL, the median paired difference was 81.251 µs and the paired-difference p95 was 270.333 µs. The baseline p95 changed from the earlier trial, so the paired differences describe this session. PostgreSQL keeps product G5 **BLOCKED**. Next, assess a localized reduction in lexer token allocation for the remaining normalization cost measured in ABBA, and verify golden fingerprints, unavailable reasons and JDBC behavior. Then evaluate both DBs under a new test ID and one-run approval.

### Lexer word allocation candidate

`OBSERVE-LEXER-WORDS-01` writes the lowercase bytes of unquoted ASCII words directly to the normalization buffer. Special handling requires exact word boundaries, and sign handling inspects the preceding token's normalized bytes. Both the previous and candidate lexers passed the same 291 Observe assertions. Checks covered golden fingerprints and query IDs, adjacent quotes and signs, administrative keywords, and rejection precedence. Core smoke, Java 17 target compilation, 213 JDBC adapter assertions, 10 H2 compatibility checks, and cleanup also passed. A separate one-run approval bound all 11 inputs shared with the functional evidence. [Functional evidence](../../evidence/PRODUCT-G5-PERFORMANCE-OBSERVE-LEXER-WORDS-01-CONTRACTS.json) · [Official one-run approval](../../evidence/PRODUCT-G5-PERFORMANCE-OBSERVE-LEXER-WORDS-01-APPROVAL.json)

On 2026-11-25, the approved official trial ran once after seven level-1 memory pressure readings five seconds apart. Each DB completed 208 queries and row checks, with zero errors or mismatches and 104 Observe events. The verifier recalculated p95 from 96 samples per arm and confirmed shutdown of both fixture DBs and their process groups and removal of 1,162 temporary files. [Official measurement evidence](../../evidence/PRODUCT-G5-PERFORMANCE-OBSERVE-LEXER-WORDS-01-RESULT.json)

| Profile | Baseline p95 (µs) | Observe p95 (µs) | Change | NFR-02 |
|---|---:|---:|---:|---|
| PostgreSQL | 419.334 | 494.500 | +17.9251% | FAIL |
| MySQL | 1722.250 | 2031.375 | +17.9489% | FAIL |

The PostgreSQL median paired difference was 82.000 µs, close to 81.251 µs for the preceding candidate. MySQL baseline p95 shifted from 1,119.959 to 1,722.250 µs. Isolating the source change calls for an interleaved comparison of both candidates in one session, with separate measurements of normalization allocation and JDBC execution time. Preparing that comparison with pinned inputs comes next. Product G5 remains **BLOCKED**, and Oracle preflight follows official acceptance on both DBs.

### Crossover of normalization allocation and JDBC execution

`OBSERVE-LEXER-CROSSOVER-01` pins the 23 approved inputs for each of `bf2b0ab` and `4bbbc8a`. PostgreSQL and MySQL run in sequence. Each profile uses one JVM, one physical JDBC connection, and one shared JdbcTemplate. Both candidates query the same row consecutively. Each of four blocks warms up four pairs and measures 16. Each of eight rows is measured once in each candidate order per block. The plan allows 160 starts per DB, 320 total, one in flight, at most eight starts per rolling second, at least 125 ms between starts, and 300 seconds overall.

Normalization allocation is the approximate bytes allocated on the current JVM thread between lexer creation and fingerprint hashing. JDBC execution measures only the delegated `PreparedStatement.executeQuery()` call in nanoseconds. Verification recomputes the per-block medians and paired differences for both metrics, and checks rows, events, fingerprints, owned process shutdown and temporary-file cleanup. [JDK 17 ThreadMXBean](https://docs.oracle.com/en/java/javase/17/docs/api/jdk.management/com/sun/management/ThreadMXBean.html)

Use `python3 -B tools/release-performance/run-lexer-crossover.py proposal` to obtain the plan hash. The `prepare` mode checks pinned sources and DB binary identity, compiles both lexers in temporary Java sources, and checks instrumentation and fingerprint agreement offline. Run `run` after separate one-run approval and seven consecutive level-1 pressure checks five seconds apart, then recalculate with `verify`. The crossover informs candidate selection for official acceptance.

Guarded preparation **passed**. Both lexers compiled for Java 17. The JVM instrumentation, synthetic JDBC delegation, matching events, 32 offline tests, Core smoke and cleanup passed. [Preparation evidence](../../evidence/PRODUCT-G5-OBSERVE-LEXER-CROSSOVER-01-PREPARATION.json)

The approved crossover ran once on 2026-11-25. Verification confirmed 160 queries, row checks and Observe events per DB, and 64 measured pairs per DB. Fingerprints and query IDs agreed. Both fixtures and their owned process groups stopped, and cleanup removed 1,181 temporary files. [Crossover approval](../../evidence/PRODUCT-G5-OBSERVE-LEXER-CROSSOVER-01-APPROVAL.json) · [Crossover evidence](../../evidence/PRODUCT-G5-OBSERVE-LEXER-CROSSOVER-01-RESULT.json)

Median normalization allocation fell from 792 to 288 B in all eight PostgreSQL and MySQL blocks (−504 B, −63.6%). Block medians of paired JDBC delegation deltas ranged from −19.416 to +24.062 µs on PostgreSQL and −1.687 to +10.604 µs on MySQL. Three of four blocks on each DB showed increases. The reproducible allocation reduction supports selecting the current lexer. The JDBC cause remains undetermined. Official end-to-end p95 is evaluated separately under `OBSERVE-LEXER-WORDS-02`.

### Official acceptance of the crossover-selected candidate

`OBSERVE-LEXER-WORDS-02` used the same 23 official input hashes as `OBSERVE-LEXER-WORDS-01`. Core smoke, 291 Observe assertions, 213 JDBC adapter assertions, and ten H2 compatibility checks passed under the new ID. The approval bound the 11 inputs shared with the functional evidence. [Functional evidence](../../evidence/PRODUCT-G5-PERFORMANCE-OBSERVE-LEXER-WORDS-02-CONTRACTS.json) · [Official one-run approval](../../evidence/PRODUCT-G5-PERFORMANCE-OBSERVE-LEXER-WORDS-02-APPROVAL.json)

On 2026-11-25, the official trial ran once after seven level-1 memory pressure readings five seconds apart. Each DB completed 208 queries and row checks, with 104 events and zero errors or mismatches. Verification recalculated p95, confirmed shutdown of both DBs and their process groups, and checked removal of 1,162 temporary files. [Official evidence](../../evidence/PRODUCT-G5-PERFORMANCE-OBSERVE-LEXER-WORDS-02-RESULT.json)

| Profile | Baseline p95 (µs) | Observe p95 (µs) | Change | NFR-02 |
|---|---:|---:|---:|---|
| PostgreSQL | 612.708 | 800.584 | +30.6632% | FAIL |
| MySQL | 1,764.417 | 1,797.375 | +1.8679% | PASS |

PostgreSQL baseline p95 shifted from 419.334 to 612.708 µs across official trials with the same product inputs. The median paired difference in this run was 104.875 µs. Next, characterize PostgreSQL baseline variation in the same session and separate Observe connection and statement wrappers, event creation and delivery, and JDBC delegation to narrow the remaining cost. Verify the resulting candidate before another separately approved official trial. Oracle preflight follows official acceptance on both DBs.

### PostgreSQL cap analysis and repeated JDBC costs

With identical official inputs, baseline PostgreSQL p95 moved from 419.334 to 612.708 µs, a 46.1% change. The latest run allowed 30.635 µs of additional latency at +5%, and the measured p95 difference was 187.876 µs. The median paired difference in that run was 104.875 µs. The trial shows baseline variation alongside additional latency on the Observe path. In the older segment diagnosis, block medians for proxy creation ranged from 18.271 to 33.604 µs. JDBC delegation also showed large differences in the slowest Observe pairs. The evidence cannot isolate the latest tail latency to one product segment. [Official samples](../../evidence/PRODUCT-G5-PERFORMANCE-OBSERVE-LEXER-WORDS-02-RESULT.json) · [Historical segment evidence](../../evidence/PRODUCT-G5-POSTGRES-OBSERVE-ABBA-02-RESULT.json)

`OBSERVE-JDBC-HOTPATH-01` reuses one immutable observation for matching implicit query ID and fingerprint metadata. Each execution delivers its current reason through the synchronous callback. JDBC proxies reuse standard interface setup and create a separate wrapper on every checkout and preparation. Positional `setInt(int,int)` and `setQueryTimeout(int)` delegate directly, while Callable names and null arguments follow the existing delegation. Fingerprints, reasons, event order and count, original JDBC results, and exception identity passed verification.

Core smoke, Java 17 target compilation, 299 Observe assertions, 239 adapter assertions, 10 H2 compatibility checks, seven offline tests, and cleanup passed. Prior official evidence was revalidated, and all 11 inputs shared between the candidate contracts and official proposal matched. Official acceptance for the new candidate is **NOT RUN** under the existing +5% criterion. [Functional evidence](../../evidence/PRODUCT-G5-PERFORMANCE-OBSERVE-JDBC-HOTPATH-01-CONTRACTS.json)

### Separating baseline variation and candidate effects on one PostgreSQL session

`OBSERVE-PG-HOTPATH-DIAG-01` binds the previous lexer at `030a69a` and the JDBC candidate at `4d1bc0b` to the official approval and contract hashes. One JVM and one physical connection run the same row through baseline A, baseline B, previous Observe, and current Observe in balanced order. The two baseline labels share one JdbcTemplate. The measured schedule balances positions and preceding paths for every row. Four blocks each run two warm-up groups and eight measured groups, with 160 starts, 32 measured groups and 80 events.

Intervals cover the full call, connection and statement wrapper creation, fingerprint and ID generation and observation metadata, event delivery, and JDBC prepare and execute. Residual time is calculated per sample. The summary reports absolute baseline A/B variation, the difference between candidates, and the difference between current Observe and the mean of both baselines within a group. It attributes the two slowest current Observe calls using their corresponding groups. Official p95 acceptance uses the existing two-DB runner.

The `prepare` mode of `python3 -B tools/release-performance/run-pg-hotpath-diagnostic.py` compiled both variants in temporary space and checked timer boundaries, events, fingerprints, IDs, and row agreement across the four paths on one H2 row. All 32 offline tests, Core smoke, and guarded cleanup passed. Missing one-run approval blocks `run` before PostgreSQL startup. A live run permits one query in flight, eight rolling starts per second, a minimum 125 ms between starts and 300 seconds overall, with seven level-1 pressure readings five seconds apart. [Guarded preparation evidence](../../evidence/PRODUCT-G5-OBSERVE-PG-HOTPATH-DIAG-01-PREPARATION.json)

On 2026-11-25, initial host memory pressure returned from level 2 to normal, and the guard confirmed seven level-1 readings. The approved isolated PostgreSQL run verified 160 queries and rows, 80 Observe events, 32 measured groups, and a minimum start spacing of 125.061958 ms. The rolling rate was at most eight starts per second. PostgreSQL, its process group, and the client exited, and cleanup removed 1,023 temporary files. [One-run approval](../../evidence/PRODUCT-G5-OBSERVE-PG-HOTPATH-DIAG-01-APPROVAL.json) · [Measured evidence](../../evidence/PRODUCT-G5-OBSERVE-PG-HOTPATH-DIAG-01-RESULT.json)

The absolute baseline A/B full-call difference had a median of 97.437 µs and a p95 of 1,505.750 µs. JDBC execution alone measured 88.167 µs and 1,482.583 µs, respectively. The three groups with the largest full-call A/B differences had total differences of 3,313.792 / 1,505.750 / 752.125 µs and corresponding JDBC differences of 3,306.625 / 1,482.583 / 711.375 µs. Twenty-nine of 32 groups exceeded the preceding official trial's +5% allowance of 30.635 µs. This comparison informs repeatability assessment. [Previous official evidence](../../evidence/PRODUCT-G5-PERFORMANCE-OBSERVE-LEXER-WORDS-02-RESULT.json)

The current candidate's median full-call difference from the previous candidate was −11.396 µs, with two faster and two slower blocks. Metadata and fixture event delivery improved in all four blocks, with median differences of −6.959 µs and −11.896 µs. The median full-call difference between the current candidate and the mean of the two baselines was +126.771 µs. Retain the current candidate's functional and segment evidence. Next, secure an isolated or idle test window, confirm repeatability of the identical baseline paths, and perform separately approved official +5% acceptance on both DBs after the measurement environment is stable.

### PostgreSQL identical baseline repeatability

`OBSERVE-PG-BASELINE-AA-01` retains the current `OBSERVE-JDBC-HOTPATH-01` source and runs both labels through the baseline. A and B share one JVM, physical connection, and JdbcTemplate. Each pair queries the same row in A/B or B/A order. Four blocks each run two warm-up pairs and eight measured pairs, for 80 starts and 32 measured pairs. The diagnostic uses PostgreSQL 17.11, JDBC 42.7.14, and the same official baseline query. The limits remain one in flight, at most eight starts per rolling second, at least 125 ms between starts, and 300 seconds overall.

This local repeatability diagnosis passes when the A/B p95 gap is at most 5% of the mean of their p95 values and the p95 absolute paired difference is at most 30.635 µs, the prior official trial's +5% allowance. The diagnosis also requires an observed quiet host window. Seven consecutive five-second intervals must show at least 90% aggregate CPU idle and memory pressure level 1 before launch. During the run, continuous samples must show at least 80% aggregate CPU idle, including the fixture's CPU use, and normal memory pressure. Aggregate CPU indicates observed contention. Official two-DB +5% acceptance continues to use the existing runner. [macOS CPU counters](https://github.com/apple-oss-distributions/xnu/blob/main/osfmk/mach/host_info.h)

Guarded preparation passed Java 17 target compilation and two baseline queries on H2. Candidate and previous official input hashes were preserved. [Preparation evidence](../../evidence/PRODUCT-G5-OBSERVE-PG-BASELINE-AA-01-PREPARATION.json)

On 2026-11-25, 21 samples were recorded in three 35-second windows. Aggregate CPU idle ranged from 2.26% to 55.38%. Four samples had memory pressure level 1. No window qualified, so the diagnosis ended **NOT RUN** before PostgreSQL startup or A/A queries. The one-run approval remains unconsumed. The same approval can be used by `run` when a quiet window is available. [One-run approval](../../evidence/PRODUCT-G5-OBSERVE-PG-BASELINE-AA-01-APPROVAL.json) · [Host preflight](../../evidence/PRODUCT-G5-OBSERVE-PG-BASELINE-AA-01-PREFLIGHT.json)

The resumed observation that day collected 119 five-second intervals over 595.9 seconds. CPU idle ranged from 11.99% to 76.36%, with zero intervals at or above 90%. Memory pressure was normal in 92 intervals. The guarded runner and PostgreSQL did not start, and the existing one-run approval remains available. [Resumed host preflight](../../evidence/PRODUCT-G5-OBSERVE-PG-BASELINE-AA-01-RESUME-20261125T061753Z.json)

The second resumed observation collected 119 five-second samples over 596.0 seconds. CPU idle ranged from 0.06% to 74.66%, with zero samples at or above 90%. Memory pressure was level 1 in 69 samples. Neither of the two resumed observations, totaling 238 samples, found a qualifying window. The guarded runner did not start and the approval remains available. [Second resumed host observation](../../evidence/PRODUCT-G5-OBSERVE-PG-BASELINE-AA-01-RESUME-20261125T063201Z.json)

The third resumed observation collected 119 five-second samples over 596.1 seconds. CPU idle ranged from 0.84% to 79.00%, and memory pressure was level 1 in 96 samples. Across all three resumed observations, zero of 357 samples reached 90% CPU idle. The evidence reconciled with the original plan and approval, and neither a run claim nor a PostgreSQL result exists. The live diagnosis remains **NOT RUN**. Resume with the existing approval when competing host work has subsided and the seven consecutive idle samples qualify. [Latest host observation](../../evidence/PRODUCT-G5-OBSERVE-PG-BASELINE-AA-01-RESUME-20261125T070311Z.json)

On the fourth resumed observation, 119 five-second samples over 596.0 seconds showed 0.11% to 76.53% CPU idle, with normal memory pressure in 104 samples. Across four resumed observations, zero of 476 samples reached 90% CPU idle. The live trial remains **NOT RUN**. The approval remains available for the next quiet window. [Fourth host observation](../../evidence/PRODUCT-G5-OBSERVE-PG-BASELINE-AA-01-RESUME-20261125T072322Z.json)

The fifth resumed observation collected 119 five-second samples over 596.0 seconds. CPU idle ranged from 15.45% to 78.67%, with normal memory pressure in 96 samples. Across all five resumed observations, zero of 595 samples reached 90% CPU idle. PostgreSQL A/A is **NOT RUN** and the one-run approval remains available. [Latest host observation](../../evidence/PRODUCT-G5-OBSERVE-PG-BASELINE-AA-01-RESUME-20261125T104924Z.json)

On 2026-11-26, `OBSERVE-PG-BASELINE-AA-ACTIVE-HOST-01` used the one-run waiver of the CPU idle floors. The original memory checks and resource bounds applied. The isolated PostgreSQL trial completed 80 queries and 32 measured pairs. CPU idle during the run ranged from 25.93% to 68.16%. The two path p95 values were 532.459 µs and 508.083 µs, a gap of 4.6853% of their mean. The paired absolute difference p95 was 165.459 µs against the 30.635 µs noise budget, yielding **NOT REPRODUCIBLE**. The result and cleanup verified successfully. Official performance acceptance remains NOT RUN. [Live result](../../evidence/PRODUCT-G5-OBSERVE-PG-BASELINE-AA-ACTIVE-HOST-01-RESULT.json)

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

Product G5 remains **BLOCKED**. For `OBSERVE-LEXER-WORDS-02`, official p95 failed at +30.6632% on PostgreSQL and passed at +1.8679% on MySQL. The Oracle pool and recovery proof needs a refresh against current inputs, and Oracle concurrency and instance crash recovery remain **NOT RUN**. Native SQL Server G5 requires an isolated Intel or AMD x86-64 Linux host. Formal release remains **BLOCKED**. [Current performance evidence](../../evidence/PRODUCT-G5-PERFORMANCE-OBSERVE-LEXER-WORDS-02-RESULT.json) · [Prior evidence assessment](../../evidence/PRODUCT-G5-ACCEPTANCE.json) · [Release gate](../../evidence/PHASE6-GATE.json)

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
