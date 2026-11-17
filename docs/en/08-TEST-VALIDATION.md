# Validation Plan, Matrix & Quality Gates

English | [한국어](../ko/08-TEST-VALIDATION.md)

## 1. Test Categories

| Type | Scope | Current Status |
|---|---|---|
| JDK-only core smoke | SQL rendering, bind order, identifier, allowlist, multi-DS guard | **Actually executed: PASS** |
| Spring Boot 3 mixed demo | JPA+MyBatis+JdbcTemplate, flush, rollback (H2) | **NOT RUN** (no Gradle/network) |
| PostgreSQL real DB | CRUD/tx/collation/time | NOT RUN |
| MySQL real DB | CRUD/tx/collation/time | NOT RUN |
| SQL Server real DB | CRUD/tx/collation/time | NOT RUN |
| Oracle real DB | CRUD/tx/collation/time | NOT RUN |
| Legacy SQL translator | Parser + safe rewrite + result equivalence | Not implemented |
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
