# Requirement → Design → Implementation → Test → Evidence

English | [한국어](../ko/16-TRACEABILITY.md)

| Requirement | Design | Actual source | Test | Status |
|---|---|---|---|---|
| FR-001 Compiler SPI | API-SPEC §2 | core/src/main/java/dev/udak/core/SqlCompiler.java | CoreSmokeTest compiler | PASS |
| FR-003 Basic Dialect subset | DBMS-COMPATIBILITY | core/src/main/java/dev/udak/core/BasicSqlCompiler.java | CoreSmokeTest five vendors | SQL render PASS only |
| FR-004 Identifier/Binding | SECURITY | core/src/main/java/dev/udak/core/BasicSqlCompiler.java | CoreSmokeTest injected identifier/invalid limit | PASS |
| FR-009 Approval Guard | LEGACY-COMPATIBILITY | core/src/main/java/dev/udak/core/ApprovedRewriteGuard.java | CoreSmokeTest exact hash + target mismatch | PASS gate only |
| FR-010 Multi-DS risk | TRANSACTION-CONSISTENCY | core/src/main/java/dev/udak/core/ConsistencyGuard.java | CoreSmokeTest multi-DS | PASS (existing static Core check). See P4-CORE, P4-SPRING and P4-TX for the separate Phase 4 modules |
| FR-005~007 Legacy Observe | LEGACY-COMPATIBILITY | observe-core/, legacy-observe/ | ObserveContractTest / LegacyObserveAdapterContractTest / LegacyCompatibilityTest | PASS (verified scope) |
| FR-002 Minimal API | API-SPEC §8 | udak-api/src/main/java/dev/udak/api/CrudClient.java | CrudApiContractTest | MINIMAL PASS; full Fluent API NOT IMPLEMENTED |
| FR-011 DB compatibility report | DBMS-COMPATIBILITY | db-testkit/ | DatabaseFoundationTest | FOUNDATION / MINIMAL REAL G2 PASS |
| FR-012 Approved SQL Rewrite runtime | LEGACY-COMPATIBILITY | rewrite-core/ · rewrite-jsqlparser/ · rewrite-jdbc/ | rewrite-testkit/ · tools/run-phase5.py | G4 PASS (fixed fixture) |
| Mixed tx demo | TRANSACTION-CONSISTENCY | spring-boot-demo/.../MixedUserService.java | MixedUserServiceTest.java | NOT RUN |

## Phase 1 execution plan (2026-11-17)

| Requirement ID | Scope | Test/verification plan | Status |
|---|---|---|---|
| P1-ENGINE / T-002 | Compare jOOQ, Calcite and JSqlParser capabilities, JDK, four-DBMS scope and licenses | Verify official sources and pinned artifact license/dependencies/checksum; record selection and distribution conditions | PASS |
| P1-SPI / FR-001 | Replaceable SqlCompiler contract | Run the same contract against the basic implementation and external-parser provider; binding order, no value inlining, immutable lists, invalid input/syntax rejection | PASS |
| P1-PROVIDER / FR-003·004 | External-library integration PoC outside Core | Java 17 compilation with a pinned artifact and actual parser calls; five rendering profiles and failure paths. Exclude claims of real-DB support or a complete translator | PASS |
| P1-HARNESS | Reproducible bounded execution, evidence and automatic cleanup | Preserve Core smoke; bound time/CPU/JVM/downloads/files for Phase 1 checks, success/failure cleanup and document/evidence verification | PASS |

Completion requires PASS for the comparison, selected-artifact license checks, SPI contracts and external integration tests. Real databases, the Spring demo, commercial-engine purchases/product-distribution approval, and performance/load tests are outside this task.

## Current evidence

## Phase 2 execution plan (2026-11-17)

| Requirement ID | Scope | Test/completion criteria | Status |
|---|---|---|---|
| P2-API / FR-002·014 / T-006 | Pure-Java minimal CRUD/Query contracts | Per-table identifier allowlists, deterministic binds, no value inlining, no updates/deletes without a PK, explicit RowMapper/count/cardinality checks | PASS (foundation scope) |
| P2-EXEC / FR-010 / T-008 | Spring-aware JDBC Executor | Actual Spring JDBC/H2 CRUD, SQL NULL/binding, participation in Spring commit/rollback on one DataSource, resource release and sensitive exception protection | PASS (foundation scope) |
| P2-DB-BASE / FR-003·011 / T-009·010 | Four-DBMS real-environment verification foundation | PostgreSQL/MySQL/SQL Server/Oracle drivers, DDL and metadata/CRUD/transaction scenarios with explicit executed/not-run gates. H2 cannot substitute for four-real-DB evidence | PASS (foundation scope) |
| P2-HARNESS | Pinned dependencies, bounds, evidence and cleanup | Checksum/license checks, Java 17-targeted compilation, time/CPU/memory/file limits, Core/Phase 1 regression, automatic cleanup and documentation consistency | PASS (foundation scope) |

This request completes the minimal API, actual Spring JDBC Executor and four-DBMS verification **foundation**. Profiles without a dedicated configured real database remain NOT RUN; G2 (four-real-DB verification) has a separate completion decision. Existing containers, databases and secret configuration remain unchanged.

[PHASE2-VALIDATION.json](../../evidence/PHASE2-VALIDATION.json) — minimal API, actual Spring JDBC/H2 and four-DBMS foundation PASS. The foundation runner keeps non-connecting inventory mode; actual minimal G2 PASS is recorded in [managed results](20-MANAGED-G2-RESULTS.md); see [detailed results](18-CRUD-JDBC-VALIDATION.md).

[PHASE1-VALIDATION.json](../../evidence/PHASE1-VALIDATION.json) — PASS for Core smoke, 74 basic and 83 external contract assertions, artifact/license checks and resource/cleanup verification. See [Phase 1 results](14-POC-RESULTS.md) for scope and unexecuted items.

`evidence/core-smoke-output.txt` — output from actual `javac`/`java` execution.

## Real G2 execution plan (2026-11-17)

| Requirement ID | Scope | Tests and completion criteria | Status |
|---|---|---|---|
| P2-G2-DRIVER | Pin four dedicated JDBC artifacts, versions and licenses | Verify official licenses, JAR/POM checksums, Java 17 baseline and required dependencies. Separate test use from product redistribution approval | PASS (artifact/contract scope only) |
| P2-G2-EVIDENCE | Real server/driver identity and safe result evidence | Execute approved providers only; verify product, numeric versions and pinned artifacts, CRUD/NULL/page/bind/commit/rollback and owned fixture cleanup; no H2 substitution | PASS (artifact/contract scope only) |
| P2-G2-LIVE | Dedicated PostgreSQL, MySQL, SQL Server and Oracle environments | All four profiles must execute and pass result mapping. Missing connectivity, licensing or safety prerequisites mean NOT RUN and incomplete G2 | NOT RUN |

Dedicated connections must come from an external `RealDatabaseProvider` that never prints secret values. Do not extract connections by reading secret files or existing service accounts. Without approved connections, real DB validation and G2 remain incomplete.


2026-11-17 preparation record: existing regressions, pinned driver loading and safe evidence contracts PASS. Without dedicated connections, all four real profiles are NOT RUN and G2 is INCOMPLETE. See [conditions](19-REAL-DB-G2.md) and [actual evidence](../../evidence/G2-VALIDATION.json).

## Dedicated provider and VM validation continuation (2026-11-18)

| Requirement ID | Scope | Tests and completion criteria | Status |
|---|---|---|---|
| P2-G2-PROVIDER | Prepare dedicated DataSource providers directly | Inject dedicated runtime connections without reading secret files or printing values; register four ServiceLoader providers; verify approval, connection timeout and default log suppression | PASS (minimal functional scope) |
| P2-G2-ENV | Prepare Parallels VM and isolated DB environments | Verify CPU architecture, OS, resources, server images/use rights; bound ownership, health, execution and cleanup evidence; preserve existing VMs/databases/data | PASS (minimal functional scope) |
| P2-G2-LIVE | Sequential real execution on four DBMSs | Actual products/versions, 10 contracts and fixture cleanup pass on all four; unexecuted or failed profiles prohibit completion | PASS (40 checks; native platform NOT RUN) |

The user authorized using Parallels VM and directly preparing necessary environments. Run only bounded dedicated environments; do not extract or delete existing VM/database/secret configuration. Record architectural/operational constraints with evidence and never substitute H2 for real execution.

Completion evidence: [G2-REAL-VALIDATION.json](../../evidence/G2-REAL-VALIDATION.json). Two batches (SQL Server and the remaining three) used identical source, driver and image inputs. Existing VMs were not started/modified; four new dedicated Docker DBs ran sequentially, stopped and were preserved. Next: FR-005~007 / T-011~013 Observe and legacy-access compatibility.

## Phase 3 Observe and mixed-access execution plan (2026-11-18)

| Requirement ID | Scope | Tests and completion criteria | Status |
|---|---|---|---|
| P3-OBS / FR-005~008 / T-011~013 | JPA/Hibernate, MyBatis and JDBC Observe adapters and non-sensitive events | Preserve original SQL/arguments/results/exceptions/cache keys; expose no raw SQL, bind/literal values, connection/account details or original exceptions; stable fingerprints/query IDs and listener failure isolation | PASS (verified framework/version scope) |
| P3-COMPAT / FR-005~007·010 | Same-DataSource flush/cache/commit/rollback compatibility | Actual Hibernate/Spring JPA, MyBatis-Spring and JdbcTemplate; existing Entity/Repository/Mapper/service; visibility before/after flush, JPA/MyBatis stale cache with explicit refresh/clear, commit and exception rollback | PASS (verified framework/version scope) |
| P3-HARNESS | Pinned dependencies, licenses/checksums, bounded execution, regression and cleanup | Preserve Core/existing contracts, Java 17 target, sequential bounded JVM/network, automatic owned workspace cleanup with original evidence retention, bilingual consistency | PASS (verified framework/version scope) |

Observe performs no automatic flush, cache synchronization or SQL rewrite. Preserve exact-SQL approval hash semantics. Mark only executed framework/database combinations PASS; load/performance and unexecuted combinations remain separately NOT RUN.

Completion evidence: [PHASE3-GATE.json](../../evidence/PHASE3-GATE.json). H2 10 and the same 10 on each real DB (40 real scenarios) PASS. Event/adapter 202/188 and existing Core 74 assertions were verified. Follow [results](21-LEGACY-OBSERVE-RESULTS.md) for observation gaps, original data/pool ownership, SQL Server operational limits and Phase 4.

## Phase 4 transaction diagnostic plan (2026-11-18)

| Requirement ID | Scope and allowed paths | Tests and completion criteria | Status |
|---|---|---|---|
| P4-CORE / FR-010 / T-014 / NFR-03·NFR-06 | JDK-only immutable diagnostics and execution-policy model in consistency-core/ | Positive/negative configuration and transaction-state contracts, explicit REPORT_ONLY/BLOCK policy, non-sensitive enum reports, no automatic retry for uncertain outcomes | PASS (123 policy assertions) |
| P4-SPRING / FR-010 / T-014 | Explicit DataSource/TxManager/JPA/MyBatis/JDBC configuration and current-thread diagnostics in consistency-spring/ | Detect multiple resources, incorrect managers and resource mismatches without connecting, running SQL or scanning all beans; preserve original settings and transaction lifecycle | PASS (52 Spring wiring assertions) |
| P4-TX / FR-010 / T-014 | Actual Spring/H2 transaction tests in consistency-testkit/ | REQUIRED participation/rollback-only, REQUIRES_NEW independent commit/outer rollback, NESTED savepoint/JPA risks, readOnly/isolation/timeout/uncertain-outcome diagnostics, existing Phase 3 H2 regression | PASS (9 Spring/H2 scenarios + 1 policy case, 205 assertions and 10 legacy H2 regression scenarios) |
| P4-HARNESS | tools/run-phase4.py, tools/verify-phase4.py, verifier tests, evidence/PHASE4-*.json, settings.gradle.kts, README*.md and paired docs/en/ and docs/ko/ documents | Java 17, pinned Phase 3 dependencies, sequential bounded JVMs, automatic cleanup, reject altered/missing evidence, bilingual consistency and Core smoke | PASS (automatic cleanup, 11 verifier checks and regressions) |

Preserve existing core/, Phase 3 Java/harnesses and dependency manifests so that G2/G3 evidence remains valid. Phase 4 diagnoses explicitly supplied configuration and the current thread. Starter discovery, XA/multi-DB atomicity, automatic flush/cache synchronization and SQL translation are outside scope. New vendor-specific readOnly/isolation/timeout combinations, native SQL Server and operational recovery remain separately NOT RUN. Do not start, modify or delete the 8 existing managed DBs, data or secret configuration. No load/performance tests run.

Completion evidence is recorded in the [Phase 4 gate](../../evidence/PHASE4-GATE.json) and [detailed results](22-TRANSACTION-GUARD-RESULTS.md). T-014 completion covers explicit configuration, current-thread diagnostics and Spring/H2 contracts.

## Phase 5 approved selective translation plan (2026-11-18)

| Requirement ID | Scope and allowed paths | Tests and completion criteria | Status |
|---|---|---|---|
| P5-POLICY / FR-009·013 / T-016 / ADR-008 | JDK-only approval/evidence Registry and selective translation SPI in rewrite-core/ | Match Query ID/exact SQL/source-target/server-driver-schema/provider-runtime/evidence hashes/expiry/revocation/actual plan; default deny | LOCAL PASS (330) |
| P5-PROVIDER / FR-012 / T-015 | Limited SELECT translator using JSqlParser 5.4 in rewrite-jsqlparser/ | Allowlisted AST and full canonical source validation; equality/unique-key order/paging only, no bind inlining, exact permutation and result labels, reject unsupported clauses | LOCAL PASS (147) |
| P5-EXEC / FR-007·009·012 / T-017 | Explicit Spring JDBC selective execution in rewrite-jdbc/ and rewrite-testkit/ | Fresh approval and actual target identity per call; preserve binds/RowMapper/external transactions; zero prepare on denial, no source fallback; actual source/target/independent expected-row equality | PASS (67 + H2 323 + real DB 1,348) |
| P5-HARNESS / FR-011·013 | tools/run-phase5*.py, tools/verify-phase5.py, verifier tests, evidence/PHASE5-*.json, settings.gradle.kts, README*.md and paired docs/en/ and docs/ko/ | Reuse bounded guards/pinned dependencies; local regression/actual four-DB results, reject missing/altered evidence, automatic cleanup and bilingual parity | G4 PASS (fixed fixture) |

Preserve existing core/, Observe, Phase 1~4 sources/harnesses and frozen manifests. Revalidate and refresh the affected Phase 4 evidence (evidence/PHASE4-VALIDATION.json, PHASE4-VERIFIER-VALIDATION.json and PHASE4-GATE.json) through the same bounded harness after global module registration changes; preserve originals under .git/. Trusted callers issue production approvals separately from test approvals. Existing JPA/MyBatis remain Observe without automatic translation. Load/performance, general SQL equivalence, Boot/Gradle/XA and operational recovery remain NOT RUN. After approval of the 12-instance cap, four new databases ran under the one-active/CPU/memory/PID/time limits while preserving the original eight.

The fixed fixture passed G4 with 32 real-DB categories and 20 verifier tests (0 skips). Production approval was not granted. [G4 evidence](../../evidence/PHASE5-GATE.json). [Phase 5 results](23-SELECTIVE-REWRITE-RESULTS.md)

## Management rules

- Do not mark features COMPLETE without evidence
- Track real DBMS server verification separately from SQL snapshots
- Update related requirement/document/test/evidence links in every PR

## Work guideline change tracking (2026-11-17)

| Requirement ID | Requirement | Targets | Verification plan | Status |
|---|---|---|---|---|
| GOV-001 | Orchestrator selects models per task, minimizes delegation, and directly performs final verification | AGENTS.md, CLAUDE.md, docs/en/13-AGENT-DEVELOPMENT-GUIDE.md | Check guideline connections across the three entry points; delegate only the focused review to a subagent, then have the orchestrator check the original text | PASS |
| GOV-002 | Feature branches, inspection of all deliverables, exclusion rules, sequential PR merges, and file agreement across six references | AGENTS.md, docs/en/13-AGENT-DEVELOPMENT-GUIDE.md, .gitignore, .dockerignore | Check branch name, exclusion patterns, file list, and Markdown names; push/PR/six-reference checks are NOT RUN if no remote is configured | Guidelines/local checks PASS / remote NOT RUN |
| GOV-003 | Preserve existing Core behavior | tools/run-core-smoke.sh | Run Core smoke once through the existing runner and confirm automatic temporary-build cleanup; exclude Boot/real-DB execution | PASS |
| GOV-004 | Block security-sensitive files, raw scan results, and dumps from Git/Docker inclusion | .gitignore, .dockerignore | Test synthetic paths for blocking/allowing without opening actual sensitive files; check equivalence of the two policies | PASS |
| GOV-005 | Separate English/Korean documentation and use an English main README | README.md, README-KO.md, docs/en/, docs/ko/, AGENTS.md, CLAUDE.md | Check 17 document pairs, translation content, commands/requirement IDs, relative links, old paths, and filenames; Core smoke | PASS |

### Actual execution and limitations during initial guideline setup

- The starting point was a source bundle without `.git`. After preparing exclusion rules, local Git was initialized on `feature/20261117-project-guidelines`. There was no existing history or branch, and no arbitrary remote was registered.
- `.gitignore`: PASS for blocking 21 prohibited-path samples and preserving eight shared-deliverable samples. `.dockerignore` passed static policy inspection only; Docker build is NOT RUN.
- PASS for Korean-language/subagent/branch/six-reference/sensitive-information rules in the three guideline documents, local links, whitespace, and Markdown filenames. The initial consistency check failed its terminology judgment; the delegation heading in the guide was clarified and checked again.
- `./tools/run-core-smoke.sh`: one PASS (exit 0), with a 60-second limit, Java heap capped at 256MiB, metaspace at 128MiB, and active CPUs at two. After the existing EXIT trap ran, temporary build remnants were 0 items/0 bytes. The existing evidence file was preserved.
- The only runtimes actually executed were `javac`/`java`. Spring application/Gradle/Docker/real databases are NOT RUN. Auxiliary worktree creation/reclamation/remaining counts were all zero.
- Because no remote URL was provided, commit/push, PR merges, six-reference comparisons, and the final switch to develop are NOT RUN. Git completion event automatic-cleanup integration was neither implemented nor verified in this task; the verified automatic-cleanup scope is limited to the existing Core smoke runner.

### Security exclusions and bilingual documentation verification (2026-11-17)

- GOV-004: Tested the same 196 synthetic paths in Git and Docker. PASS: 178 sensitive paths excluded and 18 shared paths preserved. No actual sensitive files were opened. Docker patterns were checked with `github.com/moby/patternmatcher v0.6.0`; no Docker build or container was started.
- The Docker checker failed its first two runs because its temporary root and module workspace were the same directory. A module-download diagnostic passed; separating `TMPDIR` from the module workspace produced a PASS. The cause is retained in the final evidence.
- GOV-005: PASS for preserving 17 Korean originals, translating all 17 English documents, adding language-switch links, and providing the English `README.md` and Korean `README-KO.md`. Requirement IDs, versions, table/code-block structure, and local links were checked. Original-content comparison accounted separately for language links, path replacements, and the management/security sections added in this task.
- Both READMEs were corrected to reflect the included Gradle Wrapper scripts, configuration, and jar. Demo dependency resolution and execution remain NOT RUN.
- One Core smoke run passed (exit 0); the existing runner left 0 temporary files/0 bytes after automatic cleanup. The two successful matcher checks automatically removed a total of 1,184 temporary files totaling 109,755,249 bytes when their temporary workspaces closed; no temporary directory remains. Auxiliary worktree creation/reclamation/remaining counts are all zero.
- Only Java Core compilation/tests and the Go-based pattern matcher were executed. Spring, Gradle, Docker, real databases, dependency vulnerability scanning, and remote Git completion are NOT RUN. Exclusion rules do not mean vulnerabilities have been fixed or already tracked files are automatically blocked.
- Additionally checked 24 `*.example` paths inside private directories and five ordinary shared templates. All 29 cases passed in Git and Docker, with private-directory exclusion taking precedence over template exceptions. Together with the earlier checks, 220 unique synthetic paths were covered.
- Validation evidence: [REPOSITORY-VALIDATION.json](../../evidence/REPOSITORY-VALIDATION.json).

## Phase 6 work contract (2026-11-18, VERIFIED)

| Requirement ID | Implementation / allowed_paths | Tests and acceptance | Status |
|---|---|---|---|
| P6-STARTER / T-018·019 / ADR-006 | starter-boot3/, starter-boot4/, starter-testkit/, core/build.gradle.kts, udak-api/build.gradle.kts, jdbc-spring/build.gradle.kts, observe-core/build.gradle.kts, settings.gradle.kts | Separate actual Boot 3.5.16 / Boot 4.1.2 application start/close, discovery, disable, user bean backoff, DataSource ambiguity, safe settings, H2 external transactions, isolated classpaths and packaged JAR/POM consumption | PASS (3 configurations / 6 consumers) |
| P6-CLI / T-021 | udak-cli/, tools/udak-cli.py | Read-only inspect without network, DB or secret access; fixed output/exit codes; bounded input, paths, symlinks, size and sanitized failures | PASS (41) |
| P6-LOCAL-CI / T-020 | tools/run-phase6*.py, tools/verify-phase6.py, tools/test-phase6*.py, tools/phase6-*.json, tools/local-ci.py, evidence/PHASE6-*.json, .gitignore, .dockerignore | Reuse protected runners; bounded sequential execution, pinned dependencies/POM/licenses/hashes, reject missing/tampered proofs, automatic cleanup on success/failure, Core regression | PASS (13 steps / 50 verifier tests) |
| P6-RELEASE / T-020 / ADR-007 | tools/phase6-release*.json, tools/release-gate.py, README*.md, docs/en/, docs/ko/ | Reproducible candidate artifacts/checksums/SBOM/NOTICE/version/API assessment; fail closed on missing G0/G5 or operator approvals; distinguish local validation from external publication; bilingual parity | PASS (deny); formal release BLOCKED |

Preserve Phase 1–5 execution evidence and twelve stopped databases. Assess global Gradle configuration changes separately; never relabel historical execution as a new run. No GitHub Actions, new databases, load/performance tests or external artifact publication in this run. Local candidate verification and production release authorization have separate states.

[Local CI](../../evidence/PHASE6-LOCAL-CI.json) and [G6 candidate gate](../../evidence/PHASE6-GATE.json) passed. Boot 3 POM, Boot 4 POM and Boot 4 BOM each passed 79 assertions in 11 scenarios; mixed/wrong-major startup refusal passed three cases. Thirty package files were byte-identical on rebuilding. Twenty-nine external artifacts include both resolved graphs. No external publication or new database was started. G0 remains NOT GRANTED; G5 remains NOT RUN. Next: decide product licensing and the bounded G5 validation plan, then implement and authorize formal publication.

## Product expansion Phase 1 work contract

| Requirement | Allowed paths | Acceptance | Status |
|---|---|---|---|
| INV-001 / FR-008·016 | sql-inventory/ | Explicit ObservationSink integration, bounded capture, stable scoped query and test references, static declarations vs runtime observations, metadata only; fixture uses all three actual adapters | PASS (48 + 14 assertions) |
| INV-002 / FR-011·017 | tools/sql-inventory.py, tools/test-sql-inventory.py, sql-inventory/ | Compare base/head snapshots from the same scenario profile, show observed SQL shape and coverage differences, mark unknown/incomplete input, report impacted test references in JSON and PR Markdown | PASS (12 CLI tests) |
| INV-003 / FR-017 | tools/run-sql-inventory.py, evidence/SQL-INVENTORY-*.json, README.md, README-KO.md, docs/en/, docs/ko/ | Bounded local harness, existing Core smoke and actual legacy H2 regression, CLI rejection and cleanup on success/failure, bilingual reports; prior phase gates remain independently verifiable | PASS (13 stages, 10 legacy H2 cases) |

Static entries are supplied by the application test code; an unmatched or unobserved entry is not proof of SQL deletion. The catalog contains hashes, enumerations and bounded counts. Change reporting compares the observed subset and never grants rewrite approval.

[Actual execution evidence and sanitized report](../../evidence/SQL-INVENTORY-VALIDATION.json).

## Product expansion Phase 2 work contract

| Requirement ID | Allowed paths | Acceptance | Status |
|---|---|---|---|
| TXTRACE-001 / FR-008·010 | tx-trace-spring/ | Explicit registration in existing Spring transactions, SQL observations correlated with matching thread-bound resources, separate unregistered, foreign and out-of-transaction observations, capture limits and immutable metadata report | PASS (explicit Spring registration and bounded capture) |
| TXTRACE-002 / FR-010 | tx-trace-spring/ | Actual H2 mixed JPA, MyBatis and JdbcTemplate boundary, commit and rollback-only, REQUIRES_NEW suspension and resumption, JDBC savepoint and rollback request, explicit flush ordering, unknown outcomes | PASS (8 scenarios / 318 assertions) |
| TXTRACE-003 / FR-017 | tools/run-tx-trace.py, evidence/TX-TRACE-*.json, README.md, README-KO.md, docs/en/, docs/ko/ | Pinned dependencies and guarded runner, Core/Observe/Guard regression, bilingual documentation, success/failure cleanup, metadata evidence and separate Git closeout | PASS (9 stages / 20 H2 regression cases) |

Tracing observes thread-bound resources and callbacks of explicitly connected Spring local transactions. SQL observation alone does not prove execution success or physical connection identity. Savepoint rollback notifications precede the actual operation. Reports omit raw SQL, values, connection addresses, transaction names and raw exception messages.

[Trace execution and metadata timeline](../../evidence/TX-TRACE-VALIDATION.json). Next is expansion Phase 3, schema change impact and per-query live DB regression.

## Product expansion Phase 3 work contract

| Requirement ID | Allowed paths | Acceptance | Status |
|---|---|---|---|
| SCHEMA-001 / FR-008·011 | tools/schema-impact.py, tools/test-schema-impact.py | Versioned structural snapshots for column additions, removals, width, type and nullability; Phase 1 query/test references and explicit unknown or incomplete coverage | PASS (17 tests) |
| SCHEMA-002 / FR-011·013 | schema-regression/, tools/schema-native.py | Apply the change on isolated actual PostgreSQL and MySQL fixtures; compare affected queries, labels, Java mapping and nulls before and after; preserve source and execution matrix evidence | PASS (4 query and DB combinations / 196 assertions) |
| SCHEMA-003 / FR-017 | tools/run-schema-regression.py, evidence/SCHEMA-*.json, README.md, README-KO.md, docs/en/, docs/ko/ | Pinned JDBC verification, guarded sequential server execution and cleanup, Core/Inventory regression, bilingual evidence and Git closeout | PASS (Core smoke, Inventory 48, native cleanup) |

Impact uses normalized structure and explicit query dependencies. Disposable test instances preserve existing databases and the twelve managed containers. SQL Server and Oracle per-query regression has separate validation scope.

[Execution evidence](../../evidence/SCHEMA-REGRESSION-VALIDATION.json) · [Repository and cleanup verification](../../evidence/SCHEMA-REPOSITORY-VALIDATION.json). Next is expansion Phase 4, DB and driver cancellation and recovery.

## Product expansion Phase 4 work contract

| Requirement ID | Allowed paths | Acceptance | Status |
|---|---|---|---|
| RECOVERY-001 / FR-010·011 | db-recovery/ | Observe one blocked write on each isolated PostgreSQL and MySQL fixture, then verify explicit JDBC cancellation and query timeout using independent server-side observation | PASS (4 cases) |
| RECOVERY-002 / FR-010·011 | db-recovery/ | Verify transaction state, rollback, visibility and reuse of the physical session after cancellation; verify pre-commit rollback and fresh-session recovery after fixture-session loss | PASS (6 cases, 112 assertions across both requirements) |
| RECOVERY-003 / FR-017 | tools/run-db-recovery.py, tools/test-db-recovery.py, evidence/DB-RECOVERY-*.json, README.md, README-KO.md, docs/en/, docs/ko/ | Reuse the pinned JDBC artifacts and bounded native harness, require complete and sanitized evidence, run Core smoke, verify cleanup and complete the Git closeout | PASS (Core smoke, 8 protocol tests, native cleanup) |

The functional fixture ran one database and one blocked write at a time. It verified isolated PostgreSQL 17.11 with JDBC 42.7.14 and MySQL 8.0.46 with Connector/J 26.10.0. SQL Server, Oracle, pool behavior and recovery from unknown commit outcomes are NOT RUN. G5 certification is separate work.

[Execution evidence](../../evidence/DB-RECOVERY-VALIDATION.json) · [Cancellation and recovery guide](28-DB-CANCELLATION-RECOVERY.md). Next is expansion Phase 5, per-query approval and revocation history.

## Product expansion Phase 5 work contract

| Requirement ID | Allowed paths | Acceptance | Status |
|---|---|---|---|
| APPROVAL-001 / FR-012·013 / ADR-008 | approval-history/ | Retain bounded approval and revocation events linked to the Query ID, source/target and plan fingerprints, environment versions, evidence and generation; persist, reopen, query history and reject invalid state | PASS (65 Core assertions) |
| APPROVAL-002 / FR-012·013 / ADR-003 | approval-history/ | Explicitly opt in at the existing approved SELECT execution path. A revoked or superseded generation cannot admit later work, including after reopen. Exercise stale revocation, unaffected queries, in-flight admission and fresh approval | PASS (36 H2/JDBC assertions and Core admission checks) |
| APPROVAL-003 / FR-017 | tools/run-approval-history.py, evidence/APPROVAL-HISTORY-*.json, .gitignore, .dockerignore, README.md, README-KO.md, docs/en/, docs/ko/ | Guarded Core, history and H2/JDBC tests with frozen dependencies, sanitized proof, automatic scratch cleanup and Git verification | PASS (Core smoke, 8 H2 regressions, Gradle and cleanup) |

The history is owned by a single local process with exclusive file access. Application code supplies trusted, previously verified evidence to issue a grant. Query admission continues to enforce the existing expiry, version and evidence contract. The new history path was exercised on H2 2.3.232. A real-DB matrix for this path is NOT RUN.

[Execution evidence](../../evidence/APPROVAL-HISTORY-VALIDATION.json) · [Query approval and revocation history](29-QUERY-APPROVAL-HISTORY.md). Next is expansion Phase 6, release and support evidence.

## Product expansion Phase 6 work contract

| Requirement | Allowed paths | Acceptance | Status |
|---|---|---|---|
| RELEASE-001 / FR-017 / ADR-006 | tools/run-release-demo.py, evidence/RELEASE-DEMO-*.json | Execute the complete Spring Boot demo build, mixed JPA/MyBatis/JdbcTemplate tests and packaged startup on a verified JDK 17 | PASS (JDK 17.0.10, 2 tests, packaged startup and shutdown) |
| RELEASE-002 / FR-010·013 / ADR-005 | tools/release-support/, tools/run-release-support*.py, evidence/RELEASE-SUPPORT-*.json, docs/en/, docs/ko/ | Record DB and driver combinations, verify additional isolated real-DB scenarios, and retain explicit G5 and support certification boundaries | PASS (10 new approval cases and archived matrix). G5 NOT RUN, product support NOT CERTIFIED |
| RELEASE-003 / FR-017 / ADR-007 | tools/run-release-signing.py, evidence/RELEASE-SIGNING-*.json, README.md, README-KO.md, docs/en/, docs/ko/ | Verify local signature and tamper rejection, reconcile license and release evidence, and verify the publication decision with its required approvals | PASS (2 fixture signatures and 2 changed inputs rejected). G0 NOT GRANTED, release BLOCKED |

The original release support checks precede the G0 scope approval and G5 pilot. Remaining work includes product G5 and DB support certification, authorization and implementation of the publication path, and production signing and publishing. [Release support evidence](30-RELEASE-SUPPORT-EVIDENCE.md) · [Verified matrix](../../evidence/RELEASE-SUPPORT-MATRIX.json)

## Expansion Phase 6 approval scope

| Requirement | Allowed paths | Acceptance | Status |
|---|---|---|---|
| RELEASE-004 / ADR-007 | tools/phase6-approval-scope.json, tools/verify-release-approval-scope.py, evidence/RELEASE-APPROVAL-SCOPE.json, docs/en/, docs/ko/ | Reconcile the proposed project license and distribution inventory against the existing G6 candidate and dependency evidence. Record the rights holder's scope decision separately from publication authority. | Proposal verified and scope approved. |
| RELEASE-005 / FR-017 | tools/phase6-approval-scope.json, tools/verify-release-approval-scope.py, evidence/RELEASE-APPROVAL-SCOPE.json, docs/en/, docs/ko/ | Verify the proposed bounded G5 limits and scope against the existing native fixtures. Record explicit operator approval and keep execution evidence separate. | Proposal verified and one bounded pilot approved. |

[Approved scope](31-RELEASE-APPROVAL-SCOPE.md) · [Proposal verification](../../evidence/RELEASE-APPROVAL-SCOPE.json) · [Approval decision](../../evidence/RELEASE-G0-G5-DECISION.json).

| Requirement | Allowed paths | Acceptance | Status |
|---|---|---|---|
| RELEASE-006 / ADR-007 | LICENSE, NOTICE, tools/release-g0/, tools/run-g0-candidate.py, evidence/RELEASE-G0-*.json, docs/en/, docs/ko/, README.md, README-KO.md | Record the owner decision for the approved scope and rebuild the six thin modules with approved license metadata and verified archive contents | PASS (6 POMs, 18 JARs and 6 Gradle metadata files). [Candidate evidence](../../evidence/RELEASE-G0-CANDIDATE.json) |
| RELEASE-007 / FR-017 | tools/release-g5/, tools/run-g5-pilot.py, evidence/RELEASE-G5-*.json, docs/en/, docs/ko/ | Record operator approval, run the one bounded sequential native database pilot, and verify schedule, transaction outcomes, observed timings and cleanup | PASS (48 operations per DB). [Pilot evidence](../../evidence/RELEASE-G5-PILOT.json) |

| Requirement | Allowed paths | Acceptance | Status |
|---|---|---|---|
| RELEASE-008 / NFR-02 | tools/product-g5-criteria.json, tools/release-performance/, tools/run-g5-performance.py, tools/verify-product-g5.py, evidence/PRODUCT-G5-*.json, docs/en/, docs/ko/ | Freeze the Observe p95 limit of 5% above baseline, scope and measurement rules. Assess measured paired samples under an authorized plan and distinguish a missing run. | Evidence PASS. Observe p95 FAIL on PostgreSQL (+47.8143%) and MySQL (+27.3076%). |
| RELEASE-009 / FR-010·013 / ADR-005 | tools/release-pool/, tools/run-g5-pool.py, tools/verify-product-g5.py, evidence/PRODUCT-G5-*.json, docs/en/, docs/ko/ | Verify pool rollback/reset, reuse and replacement on owned real DBs under bounded functional checks. Record remaining provider, platform and recovery gaps. | PASS (4 native PostgreSQL and MySQL cases). Expanded SQL Server and Oracle NOT RUN. |
| RELEASE-010 / FR-010 / ADR-005 | tools/release-pool/, tools/verify-product-g5.py, evidence/PRODUCT-G5-*.json, docs/en/, docs/ko/ | Stop each owned native database cleanly, restart the same fixture data on loopback, and verify committed, rolled-back and new writes. | PASS (2 native PostgreSQL and MySQL cases). Crash recovery and unknown commit outcomes NOT RUN. |

[Product G5 criteria](32-PRODUCT-G5-ACCEPTANCE.md) · [Scoped decision](../../evidence/PRODUCT-G5-ACCEPTANCE.json).

| Requirement | Allowed paths | Acceptance check | Status |
|---|---|---|---|
| RELEASE-011 / FR-010·013 / ADR-005 | tools/release-failure/, tools/verify-product-g5.py, evidence/PRODUCT-G5-*.json, docs/en/, docs/ko/ | Prove abrupt termination of each owned fixture database, preservation of acknowledged commits and rejection of uncommitted data after recovery. Lose a commit acknowledgement on an isolated connection, reconcile through an independent connection, and verify the guard declines automatic retry. | PASS (4 native PostgreSQL and MySQL cases). |
| RELEASE-012 / FR-017 / ADR-005 | tools/release-provider/, tools/verify-product-g5.py, evidence/PRODUCT-G5-*.json, docs/en/, docs/ko/ | Check platform, isolation, licensing and exact DBMS/driver identity before extending SQL Server and Oracle support. Record executed cases by profile and describe any unavailable prerequisites. | Oracle Free ARM64 pool subset PASS (2). SQL Server native provider unavailable, NOT RUN. |
| RELEASE-013 / FR-010·013·017 / ADR-005 | tools/release-provider/, tools/verify-product-g5.py, evidence/PRODUCT-G5-*.json, docs/en/, docs/ko/ | Exercise bounded Oracle JDBC cancellation, timeout, physical session replacement, and recovery in isolated fixture scope. Check the dedicated SQL Server host prerequisite and reassess G5 against verified evidence. | Oracle functional coverage PASS (5). SQL Server native G5 NOT RUN. Product G5 BLOCKED. |
| RELEASE-014 / FR-010·013·017 / ADR-005 | tools/release-provider/, evidence/PRODUCT-G5-*.json, tools/verify-product-g5.py, docs/en/, docs/ko/ | Validate dedicated native-host readiness and enforce a bounded, isolated Oracle concurrency and instance-crash trial before accepting new product G5 evidence. | Preparation PASS. SQL Server host and Oracle storage/approval prerequisites pending. New DB trials NOT RUN. |
| RELEASE-015 / NFR-02 / FR-008 | observe-core/, legacy-observe/, tools/release-performance/, tools/run-g5-performance.py, tools/verify-product-g5.py, evidence/PRODUCT-G5-*.json, docs/en/, docs/ko/ | Reduce repeat Observe work while preserving metadata, JDBC forwarding, and failure isolation. Validate functional regressions, preserve the measured baseline, and verify a separately authorized candidate run. | Functional PASS (215 Observe, 196 adapter assertions and 10 H2 cases). OBSERVE-V2 p95 PostgreSQL FAIL (+26.2141%), MySQL PASS (-5.1442%). |
| RELEASE-016 / NFR-02 | tools/release-performance/, evidence/PRODUCT-G5-POSTGRESQL-ATTRIBUTION*.json, docs/en/, docs/ko/ | Measure JDBC delegation, fingerprint computation and event handling on a bounded paired PostgreSQL diagnostic. Validate timing accounting, source identity and cleanup. | Diagnostic PASS (208 calls, 96 measured pairs). OBSERVE-V2 G5 result retained. |
| RELEASE-017 / NFR-02 | observe-core/, legacy-observe/, tools/release-performance/, tools/verify-product-g5.py, tools/run-g5-performance.py, evidence/PRODUCT-G5-*, docs/en/, docs/ko/ | Reuse prepared statement observation metadata without retaining SQL or binds. Verify event identity, JDBC behavior and privacy. Analyze the PostgreSQL execute tail and run one authorized uninstrumented comparison under the OBSERVE-V2 limits. | Functional PASS (247 Observe assertions, 256 adapter assertions, 10 H2 cases). Archived tail analysis PASS. OBSERVE-REUSE workload protocol and cleanup PASS. p95 PostgreSQL PASS (+1.2345%), MySQL FAIL (+25.7722%). RELEASE-017 incomplete. Product G5 BLOCKED. [Measured results](../../evidence/PRODUCT-G5-PERFORMANCE-OBSERVE-REUSE-RESULT.json) |
| RELEASE-018 / NFR-02 | observe-core/, legacy-observe/, tools/release-performance/, tools/verify-product-g5.py, evidence/PRODUCT-G5-*, docs/en/, docs/ko/ | Attribute the MySQL tail on one bounded diagnostic with matching JDBC timers, separate HMAC and event measurements and cache counters. Validate timing accounting, privacy and cleanup. Verify any resulting optimization against the original uninstrumented two-profile criterion after new approval. | MySQL diagnostic PASS. HMAC candidate functional PASS (253 Observe assertions, 256 adapter assertions, 10 H2 cases). OBSERVE-REUSE-V2 workload protocol and cleanup PASS. p95 PostgreSQL FAIL (+30.9844%), MySQL FAIL (+9.7616%). RELEASE-018 incomplete. Product G5 BLOCKED. [Measured results](../../evidence/PRODUCT-G5-PERFORMANCE-OBSERVE-REUSE-V2-RESULT.json) · [Diagnostic evidence](../../evidence/PRODUCT-G5-MYSQL-ATTRIBUTION.json) · [Functional evidence](../../evidence/PRODUCT-G5-OBSERVE-REUSE-V2-CANDIDATE.json) |
| RELEASE-019 / NFR-02 | tools/release-performance/, observe-core/, legacy-observe/, evidence/PRODUCT-G5-*, docs/en/, docs/ko/ | Cross over plain, prior and current PostgreSQL paths on one physical session with all six orders balanced. Validate exclusive timings and matched results. Use the evidence to select a change and require a separately approved uninstrumented PostgreSQL and MySQL comparison. | Diagnostic and offline verification PASS (204 queries, 60 measured triplets). Diagnostic p95 plain/prior/current 1,374,083 / 1,622,667 / 1,527,958 ns. Retain current HMAC. Further product changes and formal two-profile comparison NOT RUN. Official NFR-02 FAIL and product G5 BLOCKED. [Diagnostic evidence](../../evidence/PRODUCT-G5-POSTGRESQL-CROSSOVER.json) |
