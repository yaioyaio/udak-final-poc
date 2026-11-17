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
| 7 | T-021 | CLI+MCP inspect | T-020 | read-only audit |

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
- [ ] Four-real-DB provider/driver setup and integration-test G2
- [ ] Actual Legacy Observe adapters
- [ ] Actual SQL Parser/Translator Provider
- [ ] Starter auto-configuration and API performance validation

## User-confirmed six phases and current progress

| Phase | Scope | Current status |
|---|---|---|
| Phase 1 | SQL Compiler SPI, external-library comparison/integration and selected-artifact license verification | Requested scope PASS; [execution evidence](../../evidence/PHASE1-VALIDATION.json) |
| Phase 2 | Minimal new API, JDBC executor and four-real-DB verification | Minimal API/Executor/foundation PASS; next is four-real-DB G2 |
| Phase 3 | JPA/MyBatis/JdbcTemplate Observe/Analyze | NOT IMPLEMENTED |
| Phase 4 | Transaction & Consistency Guard improvements | Static PoC only; baseline safety applies from Phase 1~2 |
| Phase 5 | Verified, approved selective SQL translation | NOT IMPLEMENTED |
| Phase 6 | Boot3/Boot4 Starters, CLI, local verification automation and formal distribution | NOT IMPLEMENTED; GitHub Actions prohibited |

These are execution groups matching the user phases; existing Task IDs and detailed dependencies remain valid. T-001 customer demand and T-002 real-DB/driver commercial conditions/product-distribution approval are not marked complete by this technical PoC. Follow the verified scope in [engine evaluation](17-SQL-ENGINE-EVALUATION.md) and [current results](14-POC-RESULTS.md).
