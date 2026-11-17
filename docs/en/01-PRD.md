# PRD — Product Requirements Document

English | [한국어](../ko/01-PRD.md)

## 1. Users and Problems

### Personas
- P-01 SI/SM Spring Boot developer: Maintains Oracle/MyBatis XML alongside modern JPA
- P-02 Product developer supporting multiple DBMSs: Supports customers using PostgreSQL/MySQL/SQL Server/Oracle
- P-03 DBA/architect: Standardizes SQL/transaction quality and analyzes change impact
- P-04 DevOps/QA: Tracks test results, approval records, and performance regressions

### Jobs To Be Done
- Identify SQL and execution-boundary risks before changing complex JPA/MyBatis/JDBC code.
- Precisely identify SQL that needs modification when switching DBMSs.
- Start new projects with a common API and reliable defaults.
- Retain test evidence that changed SQL performs only approved functions.

## 2. Functional Requirements (P0/P1/P2)

| ID | Feature | Priority | Acceptance Criteria |
|---|---|---|---|
| FR-001 | SQL Compiler SPI | P0 | Core compiles even when the external implementation is replaced |
| FR-002 | Basic CRUD/Query API | P0 | Explicit SELECT/INSERT/UPDATE/DELETE contracts |
| FR-003 | Four Dialects/DBMS Capabilities | P0 | Tests for a verified common SQL subset |
| FR-004 | Parameter/Identifier Guard | P0 | Block malicious identifiers and value string concatenation |
| FR-005 | Legacy JPA Observe | P0 | Existing Entity/Repository results remain identical |
| FR-006 | Legacy MyBatis Observe | P0 | Preserve Mapper and ResultMap |
| FR-007 | Legacy JDBC Observe | P0 | Preserve existing RowMapper |
| FR-008 | SQL Fingerprint/QueryID | P0 | Identify code location/hash |
| FR-009 | Approved Rewrite Guard | P0 | Block conversion of unapproved/changed SQL |
| FR-010 | Transaction Configuration Diagnostics | P0 | Warn/block multiple DSs and incorrect tx configuration |
| FR-011 | DBMS compatibility report | P1 | Separate parse/render/execution/semantic results |
| FR-012 | Actual rewrite engine integration | P1 | Actually convert only preapproved SQL |
| FR-013 | Test Evidence Registry | P1 | Link evidence to query/schema/engine/target versions |
| FR-014 | Simple CRUD Facade | P1 | Document feature boundaries by ORM or data source |
| FR-015 | Multiple DataSources | P1 | Specify tx/route per resource; prohibit claims of automatic atomicity |
| FR-016 | SQL performance/observability | P1 | Metrics/tags and traces without personal information |
| FR-017 | CI/CLI integration | P2 | Automate compatibility/policy verification |
| FR-018 | MCP agent inspection | P2 | Provide read-only SQL diagnostic tools |

## 3. Excluded from MVP

- Unlimited automatic rewriting of actual legacy SQL
- Automatic configuration or resolution of cross-DBMS 2PC/XA
- Reimplementation of Entity Manager management/Dirty checking
- Automatic data synchronization, CDC, migration
- R2DBC/reactive support

## 4. Non-functional Requirements

| ID | Non-functional Requirement | Target/Verification |
|---|---|---|
| NFR-01 | Fail closed | Block invalid approvals/bindings/identifiers |
| NFR-02 | Performance | **Target:** p95 increase within +5% on the Observe path without conversion |
| NFR-03 | Security | Do not expose SQL parameter values in logs/metrics by default |
| NFR-04 | Compatibility | Separate Boot3/Boot4 verification matrices |
| NFR-05 | Audit | Link SQL approval versions and verification evidence |
| NFR-06 | Stability | Existing service behavior remains unchanged when new modules are unused |
| NFR-07 | Portability | Define semantics only for the common SQL subset |

## 5. KPIs and Release Conditions

- Tests and evidence paths exist for every P0 requirement
- Zero cases of incorrectly marking unsupported features as supported
- Zero executions of unapproved conversions
- Mark only features that pass actual environment tests for each designated DBMS/version as released
- Verify incident rollback scenarios (disable the Bridge/immediately restore the previous release)
