# Validation Plan, Matrix & Quality Gates

English | [한국어](../ko/08-TEST-VALIDATION.md)

## 1. Test Categories

| Type | Scope | Current Status |
|---|---|---|
| JDK-only core smoke | SQL rendering, bind order, identifier, allowlist, multi-DS guard | **Actually executed: PASS** |
| Spring Boot 3 mixed demo | JPA+MyBatis+JdbcTemplate, flush, rollback (H2) | **NOT RUN** for full Boot/Gradle; programmatic business-source G3 PASS |
| PostgreSQL real DB | CRUD/tx/collation/time | PASS: minimal G2; timezone/collation NOT RUN |
| MySQL real DB | CRUD/tx/collation/time | PASS: minimal G2; timezone/collation NOT RUN |
| SQL Server real DB | CRUD/tx/collation/time | PASS: minimal G2; timezone/collation NOT RUN |
| Oracle real DB | CRUD/tx/collation/time | PASS: minimal G2; timezone/collation NOT RUN |
| Legacy SQL translator | Parser + safe rewrite + result equivalence | G4 PASS (fixed fixture) |
| Load benchmark | p50/p95 overhead | NOT RUN |

## 2. Test Matrix

- framework: new API / JPA legacy / MyBatis legacy / JDBC legacy
- database: PostgreSQL / MySQL / SQL Server / Oracle
- operation: CRUD, JOIN, PAGE, BATCH, UPSERT, timestamps, errors
- consistency: same DS mixed, multi DS divergent, retries/rollback/isolation
- versions: DB server, JDBC driver, Boot, MyBatis, Hibernate

Do not claim unconditional support for every combination with identical functionality. N/A is allowed per Capability.

## 3. Key Gates

1. G0: SQL engine/DBMS license approval
2. G1: Pass API/SPI core contracts
3. G2: Actual tests against 4 DBMSs & result mapping
4. G3: Existing JPA/MyBatis/JDBC regression tests
5. G4: Selective translation tests + approval evidence
6. G5: Concurrency/performance/cancellation/failure recovery
7. G6: Deployment/version compatibility/API breaking change assessment

Phase 6 validates G6 local packaging and checks the version/API boundary. The approved G5 native database pilot passed. Product performance criteria, remaining support validation and an authorized publishing path are still required. Formal release remains BLOCKED. [Phase 6 gates](24-STARTERS-CLI-RELEASE-GATES.md) · [Approved scope and pilot](31-RELEASE-APPROVAL-SCOPE.md)

## 4. Evidence Fields

```
requirementId, scenarioId, queryId, sqlHash, dbms, dbVersion,
driverVersion, frameworkVersion, providerVersion, schemaVersion,
testTime, inputHash, outputHash, exitCode, logsPath, reviewer
```

## 5. Actual Execution

```bash
./tools/run-core-smoke.sh
# If Gradle is installed and Maven Central is reachable:
gradle :spring-boot-demo:test
```

## 6. Criteria for Declaring Support

Validating development DSL SQL generation (strings) and actual DB execution are entirely different states. Record `COMPILED`, `RENDERED`, `EXECUTED`, `RESULT_VERIFIED`, `TX_VERIFIED`, and `PERFORMANCE_VERIFIED` separately.

## Latest real G2 evidence

[Minimal functional G2](20-MANAGED-G2-RESULTS.md): 40 checks and fixture cleanup passed on four actual DBMSs. Native SQL Server platform certification, graceful shutdown/restart recovery, comprehensive timezone/collation equivalence and performance are NOT RUN.

## Latest Phase 3 G3 evidence

[PHASE3-GATE.json](../../evidence/PHASE3-GATE.json): Core 74, Observe Core 202 and adapter contract 188 assertions, H2 same-DS 10 and four-real-DB 40 compatibility scenarios PASS. Four existing demo business sources were reused through programmatic Spring/Hibernate/MyBatis; full Boot autoconfiguration and Gradle task execution remain NOT RUN. See [detailed results and exclusions](21-LEGACY-OBSERVE-RESULTS.md). No load/performance testing was executed.

## Latest Phase 4 transaction diagnostics evidence

Explicit configuration, current-thread transaction diagnostics and actual Spring/H2 contracts passed. Policy checks passed 123 assertions, Spring wiring passed 52 and the new contracts passed 205. The new contracts cover 9 Spring/H2 scenarios and 1 unknown-outcome policy case, with all 10 legacy H2 regression scenarios passing. The new four-vendor transaction matrix, Boot autoconfiguration, Gradle, Boot 3/4, XA, operational recovery and performance/load are NOT RUN. [PHASE4-GATE.json](../../evidence/PHASE4-GATE.json), [22-TRANSACTION-GUARD-RESULTS.md](22-TRANSACTION-GUARD-RESULTS.md).

## Latest Phase 5 evidence and G4

`python3 tools/run-phase5.py` passed local policy, parser, JDBC, H2 equivalence and regression checks. Actual PostgreSQL source execution and 32 categories (1,348 assertions) across four targets passed. All 20 verifier tests passed without skips. [Phase 5 results](23-SELECTIVE-REWRITE-RESULTS.md)
