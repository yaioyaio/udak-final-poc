# Work Breakdown Structure (WBS) + PLAN / TASK / TODOLIST

English | [한국어](../ko/09-WBS-ROADMAP.md)

Estimated durations depend heavily on staffing/licenses/test infrastructure and are **not a committed schedule**. Proceed with each Phase only after passing the preceding Gate.

| Phase | Task ID | Work | Prerequisite | Deliverable/AC |
|---|---|---|---|---|
| 0 | T-001 | Validate product differentiation/demand | - | 5 customer scenarios |
| 0 | T-002 | jOOQ/Calcite/JSqlParser capability/license PoC | - | Report on commercial usability with 4 DBs |
| 1 | T-003 | Java Core, SPI design | T-002 | Compilation/replacement contract tests |
| 1 | T-004 | Schema metadata/identifier policy | T-003 | Injection/identifier tests |
| 1 | T-005 | Dialect capability | T-003 | Explicit handling of unsupported features |
| 2 | T-006 | Simple CRUD API | T-003 | CRUD contracts |
| 2 | T-007 | Fluent Query DSL | T-003 | JOIN/PAGE contracts |
| 2 | T-008 | Spring-aware JDBC executor | T-006 | Local transaction tests |
| 3 | T-009 | PostgreSQL/MySQL real DB validation | T-008 | SQL/result evidence |
| 3 | T-010 | SQL Server/Oracle real DB validation | T-008 | driver/license evidence |
| 4 | T-011 | JDBC Legacy Observe | T-008 | No business code changes |
| 4 | T-012 | MyBatis Legacy Observe | T-011 | BoundSql/mapper tracking |
| 4 | T-013 | JPA Legacy Observe | T-011 | No Hibernate changes |
| 4 | T-014 | Tx/Consistency Diagnostics | T-011 | flush/cache/DS risk report |
| 5 | T-015 | SQL parser/translator SPI | T-002 | unsupported fail closed |
| 5 | T-016 | Approval Registry/Evidence | T-015 | Invalidate on version changes |
| 5 | T-017 | SQL rewrite per query | T-016 | Real DB equivalence tests |
| 6 | T-018 | Boot3 Starter/AutoConfig | T-011 | Sample app passes |
| 6 | T-019 | Boot4 Starter/AutoConfig | T-018 | Separate Boot4 compatibility |
| 6 | T-020 | Observability/CI/release | T-017 | Quality/performance gates |
| 6–7 | T-021 | Read-only CLI inspect in Phase 6, MCP in Phase 7 | T-020 | Read-only evidence audit |

## Task Execution Template

```markdown
TASK-ID:
Linked Requirement:
Architecture/ADR:
Inputs:
Implementation Files:
Tests:
DBMS/Framework Matrix:
Security & Consistency Risks:
Evidence path:
Status: TODO / IN_PROGRESS / BLOCKED / VERIFIED
```

## TODO (Actual Current Status)

- [x] JDK Core SQL Compiler SPI/POC
- [x] ID allowlist and bind ordering smoke test
- [x] Approved translation policy gate (not a translation engine)
- [x] Multiple-DataSource configuration guard (static tests)
- [x] Spring Boot mixed example source written
- [ ] Spring Boot mixed example Gradle build/execution/tests
- [x] Minimal CRUD/Query API and actual Spring JDBC/H2 contracts
- [x] Four-DBMS fixture, driver/provider and metadata test foundation
- [x] Four-real-DB provider/driver setup and minimal functional G2 (40 checks)
- [x] Actual Legacy Observe adapters (3 verified paths)
- [x] Explicit transaction diagnostics and Spring/H2 contract checks (bounded T-014 scope)
- [x] Phase 5 limited Parser/Translator Provider local contract
- [x] Phase 5 four real-DB fixed-fixture equivalence and G4
- [x] Phase 6 Starter, CLI and protected local verification
- [ ] G5 concurrency, performance, cancellation and recovery validation

## User-confirmed six phases and current progress

| Phase | Scope | Current status |
|---|---|---|
| Phase 1 | SQL Compiler SPI, external-library comparison/integration and selected-artifact license verification | Requested scope PASS; [execution evidence](../../evidence/PHASE1-VALIDATION.json) |
| Phase 2 | Minimal new API, JDBC executor and four-real-DB verification | Minimal API/Executor and actual four-DB functional G2 PASS; next is Phase 3 Observe |
| Phase 3 | JPA/MyBatis/JdbcTemplate Observe/Analyze | PASS: 202 / 188 assertions; H2 10 + real DB 40 scenarios; next Phase 4 |
| Phase 4 | Transaction & Consistency Guard improvements | PASS: explicit configuration, current-thread policy and Spring/H2 contracts (bounded T-014 scope) |
| Phase 5 | Verified, approved selective SQL translation | G4 PASS (fixed fixture) |
| Phase 6 | Boot3/Boot4 Starters, read-only CLI, local CI and release gate | Local CI / G6 private candidate PASS, formal release BLOCKED |

These are execution groups matching the user phases; existing Task IDs and detailed dependencies remain valid. T-001 customer demand and T-002 real-DB/driver commercial conditions/product-distribution approval are not marked complete by this technical PoC. Follow the verified scope in [engine evaluation](17-SQL-ENGINE-EVALUATION.md) and [current results](14-POC-RESULTS.md).

See [managed G2 results](20-MANAGED-G2-RESULTS.md) for Phase 2 completion evidence. This minimal scope does not complete T-007 full Fluent JOIN, commercial distribution approval or support certification.

Phase 5 completed its limited rewrite implementation and validation at G4. Phase 6 covers separate Boot3 and Boot4 Starters, read-only CLI and local CI. GitHub Actions is prohibited. Formal release remains BLOCKED. [Phase 5 results](23-SELECTIVE-REWRITE-RESULTS.md) · [Phase 6 scope](24-STARTERS-CLI-RELEASE-GATES.md)

## Product expansion phases

The expansion uses the existing POC phases and gate evidence as its baseline. Each phase has its own acceptance criteria.

| Expansion phase | Scope | Acceptance criteria | Status |
|---|---|---|---|
| Phase 1 | SQL inventory and PR diff | Capture metadata from all three Observe adapters, record explicit definitions and test coverage, and compare base/head snapshots in a local PR report (`INV-001`–`INV-003`). | Implementation and local verification tracked in the [SQL inventory guide](25-SQL-INVENTORY-PR-REPORT.md). |
| Phase 2 | Transaction boundary tracing | Correlate SQL observations from JPA, MyBatis and JdbcTemplate with Spring Framework 6.2.19 local transaction boundaries and verify reporting on H2 (`TXTRACE-001`–`TXTRACE-003`). | PASS (8 scenarios). [Transaction boundary tracing](26-TRANSACTION-BOUNDARY-TRACE.md). |
| Phase 3 | Schema impact and per-query real-DB validation | Connect normalized column changes to inventory query and test hashes. Verify two affected queries on each of PostgreSQL 17 and MySQL 8.0 (`SCHEMA-001`–`SCHEMA-003`). | PASS (4 combinations). [Schema impact and regression](27-SCHEMA-IMPACT-REGRESSION.md). |
| Phase 4 | DB/driver cancellation and recovery | Verify explicit JDBC cancellation, query timeout and recovery after pre-commit session loss for the selected DB/driver pairs. Record physical session reuse and transaction outcomes (`RECOVERY-001`–`RECOVERY-003`). | PASS (PostgreSQL and MySQL, 6 cases). [Cancellation and recovery](28-DB-CANCELLATION-RECOVERY.md). |
| Phase 5 | Approval and revocation history | Retain approval and revocation history linked to the query, fingerprint, versions and evidence. Verify that revoked approvals deny subsequent rewrites (`APPROVAL-001`–`APPROVAL-003`). | PASS (Core and H2/JDBC). [Query approval and revocation history](29-QUERY-APPROVAL-HISTORY.md). |
| Phase 6 | Release and support evidence | Close G0/G5, sign and publish the release, run the complete mixed demo on an actual JDK 17, and certify DB support against the verified matrix. | Scoped G0 candidate, G5 pilot, mixed demo and local signatures PASS. Formal release BLOCKED, product support NOT CERTIFIED. [Evidence and open gates](30-RELEASE-SUPPORT-EVIDENCE.md). |

## Feature-first backlog

The 2026-11-21 decision prioritizes completing the product features and defers public publication. The existing gate evidence provides the baseline for the following work. [Next-task handoff](33-FEATURE-HANDOFF.md)

| Order | Task | Status | Scope and acceptance |
|---|---|---|---|
| 1 | NEXT-001 · Redact Core string output | PASS | `Bind`, `CompiledQuery` and `QueryDefinition` expose safe metadata in string output. Protected Core smoke verifies synthetic marker redaction, no invocation of the supplied value's `toString()`, and the existing binding contracts. |
| 2 | NEXT-002 · MyBatis Mapper XML inventory and PR report | PASS | An opt-in base/head report shows XML additions, changes, removals and dynamic substitution candidates using file, line, classification and hash. Local tests cover unsupported cases and disabled external resolution. [Mapper XML review](25-SQL-INVENTORY-PR-REPORT.md#optional-mapper-xml-review-next-002) |
| 3 | NEXT-003 · Legacy Observe adoption and coverage | PASS | Explicit Hibernate composition passed H2 OFF/ON checks for application results, rollback and observation events. Fixed `UNAVAILABLE` reason counts passed Observe, inventory and report checks. [Composition results](21-LEGACY-OBSERVE-RESULTS.md#compose-an-existing-hibernate-inspector-next-003) |
| 4 | NEXT-004 · Schema contract and environment drift | PASS (H2) | Read selected table metadata and compare normalized snapshots at the same revision. H2 verified each of the five column change kinds. External DBMS verification is NOT RUN. The independent order regression selected one affected test and excluded the unused-column control. H2 verified matching and unresolved attribution through recorded migration history and observed changes. Both reviewed static audit statements matched, covering 1 of 4 inventory entries completely by extraction alone. Both rendered stock UPDATE variants match their reviewed references. An `active` change selects only the ON path, and an unused-column change selects zero tests. Two fingerprints under one Query ID selected only the affected ON test. Missing fingerprint coverage stayed INCOMPLETE. The v2 inventory records observed test links, and swapped links under one Query ID are detected. The PR report displays gained and lost observed links per fingerprint. The order pilot maps impacted test hashes to registered replay entry points and flags incomplete evidence. One PR report selected both stock modes for independent H2 replay with verified schema hashes. [Map impacted test hashes to order regressions](25-SQL-INVENTORY-PR-REPORT.md#map-impacted-test-hashes-to-order-regressions) [Review observed test link changes per fingerprint](25-SQL-INVENTORY-PR-REPORT.md#review-observed-test-link-changes-per-fingerprint) [Verify observed fingerprint test links](27-SCHEMA-IMPACT-REGRESSION.md#verify-observed-fingerprint-test-links) [Verify dependencies for each observed fingerprint](27-SCHEMA-IMPACT-REGRESSION.md#verify-dependencies-for-each-observed-fingerprint) [Stock UPDATE regression](27-SCHEMA-IMPACT-REGRESSION.md#verify-rendered-order-stock-update-dependencies) [Schema contract](27-SCHEMA-IMPACT-REGRESSION.md#compare-schema-contracts-across-environments) |
| 5 | NEXT-005 · Adoption support and value validation | PASS (synthetic H2) · External PostgreSQL baseline PASS · Observe pending | The user-designated H2 order service passed OFF/ON and rollback comparison. One stock SQL change appeared at two observation points. The PR report shows both observations for one reviewed change. The H2 diagnostic examples distinguish successful SQL with unavailable normalization from a MyBatis cache hit. Production legacy adoption NOT RUN. [Pilot results](34-LEGACY-ADOPTION-PILOT.md#independent-order-service-pilot) The ThingsBoard CE checkout is pinned and official Maven artifacts are verified. Its isolated PostgreSQL baseline passed both existing tests. Observe OFF/ON is NOT RUN. [ThingsBoard pilot prerequisites](34-LEGACY-ADOPTION-PILOT.md#thingsboard-ce-external-pilot) |

Public registry, namespace, operational signing and publication work is **DEFERRED**. Official performance and remaining database support checks depend on their documented environment and approval conditions. [Open release and support gates](30-RELEASE-SUPPORT-EVIDENCE.md) · [Product G5 criteria](32-PRODUCT-G5-ACCEPTANCE.md)
