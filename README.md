# UDAK Final Architecture + Runnable POC (v0.1.0-poc)

English | [한국어](README-KO.md)

**UDAK: Unified Data Access & Compatibility Kit** — an **architecture and validation package** for maintaining existing Spring Boot JPA / MyBatis / JdbcTemplate applications and introducing an optional unified data access API.

> ⚠️ This is the **target architecture and an initial runnable POC**, not a final product release. The SQL compiler supports a limited syntax subset. Explicit JDBC rewrite for approved SELECT queries passed G4 on fixed H2 and four real-DB fixtures. Minimal CRUD/transaction G2 passed on four selected real-DB images; this is separate from product support certification. Expand the implementation incrementally using test evidence.

## 1. Quick start

Only JDK 17 or later is required for the Core smoke test; it has no external dependencies:

```bash
./tools/run-core-smoke.sh
```

The test compiles the Core directly with `javac` and checks SQL rendering, binding order, allowed identifiers, the approval gate for SQL rewriting, and multiple DataSource warnings.

The Spring Boot mixed-access sample requires Gradle and access to Maven Central:

```bash
./tools/run-spring-demo.sh
# Or:
# gradle :spring-boot-demo:test
# gradle :spring-boot-demo:bootRun
```

The demo illustrates JPA + MyBatis + JdbcTemplate participation in one transaction on a single H2 DataSource and the need for explicit flushing. H2 MODE=PostgreSQL is **not evidence of compatibility with PostgreSQL itself**.

Phase 1 external-parser contracts and pinned dependency/license checks (Python 3, JDK 17+, Maven Central access):

```bash
python3 tools/run-phase1.py
```

The bounded harness preserves failure evidence and cleans only its own temporary workspace. See [engine evaluation](docs/en/17-SQL-ENGINE-EVALUATION.md) and [execution results](docs/en/14-POC-RESULTS.md).

Phase 2 minimal API, Spring JDBC/H2 and four-DBMS verification foundation:

```bash
python3 tools/run-phase2.py
```

See [CRUD/JDBC validation](docs/en/18-CRUD-JDBC-VALIDATION.md) and [actual four-DB G2 results](docs/en/20-MANAGED-G2-RESULTS.md). Directly implemented dedicated providers passed 40 minimal real-DB contracts and fixture cleanup. SQL Server x86 emulation supplies functional evidence; native platform certification is NOT RUN.


Verify existing real G2 evidence only (no new server startup):

```bash
python3 tools/verify-real-g2.py
```

Use `python3 tools/run-managed-g2.py` to prepare fresh dedicated environments and rerun. It starts one database at a time and stops/preserves it afterward; first review the [resource and retention conditions](docs/en/20-MANAGED-G2-RESULTS.md).

Phase 3 Observe contracts and actual Hibernate/MyBatis/JdbcTemplate same-DataSource compatibility:

```bash
python3 tools/run-phase3.py
# Verify existing H2/real-DB evidence only (no server startup).
python3 tools/verify-phase3.py
```

Observe Core 202 and adapter 188 assertions, H2 10 and four-real-DB 40 scenarios PASS. See [results, explicit wiring and observation gaps](docs/en/21-LEGACY-OBSERVE-RESULTS.md). `python3 tools/run-phase3-real.py` creates fresh dedicated databases; first review the 12 currently retained instances and resource cap.

Phase 4 explicit transaction diagnostics and actual Spring/H2 contract checks

```bash
python3 tools/run-phase4.py
python3 tools/verify-phase4.py
```

Explicit configuration, current-thread policy and Spring/H2 validation passed. The new four-DB transaction matrix and Boot/Gradle validation are NOT RUN. [Detailed results](docs/en/22-TRANSACTION-GUARD-RESULTS.md).

Phase 5 approved selective rewrite validation

```bash
python3 tools/run-phase5.py
# Verify preserved G4 evidence without starting databases
python3 tools/verify-phase5.py
```

Local contracts, H2 equivalence and 32 verification categories across four real databases passed. All 20 verifier tests and G4 passed. [Detailed results](docs/en/23-SELECTIVE-REWRITE-RESULTS.md).

Phase 6 separate Boot Starters, local verification and release gate

```bash
python3 tools/local-ci.py
python3 tools/udak-cli.py inspect --format json
python3 tools/release-gate.py
```

Phase 6 local CI and the G6 private-candidate gate are PASS (three Boot configurations, 41 CLI tests and 50 verifier tests). The release gate remains BLOCKED and returns exit code 2. [Starter settings, protected runtime and release requirements](docs/en/24-STARTERS-CLI-RELEASE-GATES.md)

Expansion Phase 1 adds a SQL inventory and local base/head PR reports for existing Observe adapters.

```bash
python3 tools/run-sql-inventory.py
```

[Capture, compare and verify](docs/en/25-SQL-INVENTORY-PR-REPORT.md)

Expansion Phase 2 adds explicit local transaction tracing for Spring Framework 6.2.19 Observe hooks. The Spring/H2 trace passed eight scenarios and 318 assertions.

```bash
python3 tools/run-tx-trace.py
```

[Attach a trace and interpret its events](docs/en/26-TRANSACTION-BOUNDARY-TRACE.md)

Expansion Phase 3 passed normalized schema impact analysis and four per-query regressions on actual PostgreSQL and MySQL.

```bash
python3 tools/run-schema-regression.py
```

[Impact CLI inputs and fixture scope](docs/en/27-SCHEMA-IMPACT-REGRESSION.md)

Expansion Phase 4 covers bounded JDBC cancellation, timeout and session recovery on PostgreSQL and MySQL. [Fixture scope and validation status](docs/en/28-DB-CANCELLATION-RECOVERY.md)

Expansion Phase 5 adds local approval and revocation history for explicitly approved JDBC SELECT rewrites. [Usage and validation status](docs/en/29-QUERY-APPROVAL-HISTORY.md)

## 2. Product policies

- **Primary customer:** Spring Boot SI/SM and enterprise backend teams operating multiple DBMSs and frameworks.
- **New:** Simple CRUD + Fluent Query API after stabilization. The current Core is a limited compiler SPI demo.
- **Legacy:** Minimize changes to existing source code; proceed through Observe → Analyze → Approved Rewrite.
- **SQL engine:** Replaceable `SqlCompiler`/translation SPI. Adopt an external engine only after license and capability validation.
- **Transactions:** Spring manages transactions; UDAK detects configuration issues and risks. It does not guarantee atomicity across databases.
- **Target DBMSs:** PostgreSQL, MySQL, SQL Server, and Oracle. Minimal functional G2 passed on pinned images; broader support certification is separate.

### Licensing

Apache-2.0 applies to the approved UDAK-owned public source scope and six thin Maven packages at version `0.1.0-poc`. Applicable third-party notices are retained. Formal publication remains blocked. [Approved license and artifact scope](docs/en/31-RELEASE-APPROVAL-SCOPE.md#g0-project-license-and-distribution-release-004)

## 3. Documentation

| English document | Description | Korean |
|---|---|---|
| [00-EXECUTIVE-DECISIONS.md](docs/en/00-EXECUTIVE-DECISIONS.md) | Target product and differentiation | [한국어](docs/ko/00-EXECUTIVE-DECISIONS.md) |
| [01-PRD.md](docs/en/01-PRD.md) | Requirements, users, KPIs, and scope | [한국어](docs/ko/01-PRD.md) |
| [02-ARCHITECTURE.md](docs/en/02-ARCHITECTURE.md) | Logical/deployment structure, dependencies, and ADRs | [한국어](docs/ko/02-ARCHITECTURE.md) |
| [03-API-SPEC.md](docs/en/03-API-SPEC.md) | New API and Compiler/Executor/Guard contracts | [한국어](docs/ko/03-API-SPEC.md) |
| [04-DBMS-COMPATIBILITY.md](docs/en/04-DBMS-COMPATIBILITY.md) | Four-DBMS strategy and SQL semantic differences | [한국어](docs/ko/04-DBMS-COMPATIBILITY.md) |
| [05-LEGACY-COMPATIBILITY.md](docs/en/05-LEGACY-COMPATIBILITY.md) | JPA/MyBatis/JDBC adoption and approved rewriting | [한국어](docs/ko/05-LEGACY-COMPATIBILITY.md) |
| [06-TRANSACTION-CONSISTENCY.md](docs/en/06-TRANSACTION-CONSISTENCY.md) | Local/multi-database transactions and time policies | [한국어](docs/ko/06-TRANSACTION-CONSISTENCY.md) |
| [07-SECURITY-OBSERVABILITY.md](docs/en/07-SECURITY-OBSERVABILITY.md) | Security, logging, and operational metrics | [한국어](docs/ko/07-SECURITY-OBSERVABILITY.md) |
| [08-TEST-VALIDATION.md](docs/en/08-TEST-VALIDATION.md) | Test matrices, evidence, and quality gates | [한국어](docs/ko/08-TEST-VALIDATION.md) |
| [09-WBS-ROADMAP.md](docs/en/09-WBS-ROADMAP.md) | Phases, dependencies, and work items | [한국어](docs/ko/09-WBS-ROADMAP.md) |
| [10-USECASES-EVENTSTORMING.md](docs/en/10-USECASES-EVENTSTORMING.md) | Use cases and EventStorming | [한국어](docs/ko/10-USECASES-EVENTSTORMING.md) |
| [11-API-CONFIG-SCHEMA.md](docs/en/11-API-CONFIG-SCHEMA.md) | Spring configuration contracts and examples | [한국어](docs/ko/11-API-CONFIG-SCHEMA.md) |
| [12-MIGRATION-RUNBOOK.md](docs/en/12-MIGRATION-RUNBOOK.md) | Adoption and rollback procedures | [한국어](docs/ko/12-MIGRATION-RUNBOOK.md) |
| [13-AGENT-DEVELOPMENT-GUIDE.md](docs/en/13-AGENT-DEVELOPMENT-GUIDE.md) | Shared Codex / Claude Code guidance | [한국어](docs/ko/13-AGENT-DEVELOPMENT-GUIDE.md) |
| [14-POC-RESULTS.md](docs/en/14-POC-RESULTS.md) | Actual validation results and unverified items | [한국어](docs/ko/14-POC-RESULTS.md) |
| [15-MARKET-VS-EXISTING.md](docs/en/15-MARKET-VS-EXISTING.md) | Existing libraries and productization decisions | [한국어](docs/ko/15-MARKET-VS-EXISTING.md) |
| [16-TRACEABILITY.md](docs/en/16-TRACEABILITY.md) | Requirement ↔ implementation ↔ test mapping | [한국어](docs/ko/16-TRACEABILITY.md) |
| [17-SQL-ENGINE-EVALUATION.md](docs/en/17-SQL-ENGINE-EVALUATION.md) | Phase 1 engine/license selection and limits | [한국어](docs/ko/17-SQL-ENGINE-EVALUATION.md) |
| [18-CRUD-JDBC-VALIDATION.md](docs/en/18-CRUD-JDBC-VALIDATION.md) | Minimal API, Spring JDBC, four-DBMS foundation and G2 boundary | [한국어](docs/ko/18-CRUD-JDBC-VALIDATION.md) |
| [19-REAL-DB-G2.md](docs/en/19-REAL-DB-G2.md) | Pinned JDBC drivers/licenses, dedicated providers and execution policy | [한국어](docs/ko/19-REAL-DB-G2.md) |
| [20-MANAGED-G2-RESULTS.md](docs/en/20-MANAGED-G2-RESULTS.md) | Actual four-DB G2, resources, retention and next work | [한국어](docs/ko/20-MANAGED-G2-RESULTS.md) |
| [21-LEGACY-OBSERVE-RESULTS.md](docs/en/21-LEGACY-OBSERVE-RESULTS.md) | Observe adapters and flush/cache/rollback compatibility results | [한국어](docs/ko/21-LEGACY-OBSERVE-RESULTS.md) |
| [22-TRANSACTION-GUARD-RESULTS.md](docs/en/22-TRANSACTION-GUARD-RESULTS.md) | Explicit transaction diagnostics, enforcement and Spring/H2 validation | [한국어](docs/ko/22-TRANSACTION-GUARD-RESULTS.md) |
| [23-SELECTIVE-REWRITE-RESULTS.md](docs/en/23-SELECTIVE-REWRITE-RESULTS.md) | Approved selective SQL rewrite and four-real-DB G4 results | [한국어](docs/ko/23-SELECTIVE-REWRITE-RESULTS.md) |
| [24-STARTERS-CLI-RELEASE-GATES.md](docs/en/24-STARTERS-CLI-RELEASE-GATES.md) | Separate Spring Boot Starters, read-only CLI and release gates | [한국어](docs/ko/24-STARTERS-CLI-RELEASE-GATES.md) |
| [25-SQL-INVENTORY-PR-REPORT.md](docs/en/25-SQL-INVENTORY-PR-REPORT.md) | SQL inventory and base/head PR report | [한국어](docs/ko/25-SQL-INVENTORY-PR-REPORT.md) |
| [26-TRANSACTION-BOUNDARY-TRACE.md](docs/en/26-TRANSACTION-BOUNDARY-TRACE.md) | Explicit Spring transaction boundary tracing and SQL observation correlation | [한국어](docs/ko/26-TRANSACTION-BOUNDARY-TRACE.md) |
| [27-SCHEMA-IMPACT-REGRESSION.md](docs/en/27-SCHEMA-IMPACT-REGRESSION.md) | Normalized schema impact and per-query real-DB regression | [한국어](docs/ko/27-SCHEMA-IMPACT-REGRESSION.md) |
| [28-DB-CANCELLATION-RECOVERY.md](docs/en/28-DB-CANCELLATION-RECOVERY.md) | JDBC cancellation, timeout and session recovery | [한국어](docs/ko/28-DB-CANCELLATION-RECOVERY.md) |
| [29-QUERY-APPROVAL-HISTORY.md](docs/en/29-QUERY-APPROVAL-HISTORY.md) | Persistent query approval and revocation history | [한국어](docs/ko/29-QUERY-APPROVAL-HISTORY.md) |
| [30-RELEASE-SUPPORT-EVIDENCE.md](docs/en/30-RELEASE-SUPPORT-EVIDENCE.md) | Release decision, licensing and verified database support scope | [한국어](docs/ko/30-RELEASE-SUPPORT-EVIDENCE.md) |
| [31-RELEASE-APPROVAL-SCOPE.md](docs/en/31-RELEASE-APPROVAL-SCOPE.md) | Approved G0 license and artifact scope and G5 pilot limits | [한국어](docs/ko/31-RELEASE-APPROVAL-SCOPE.md) |

Maintain matching filenames in `docs/en/` and `docs/ko/`. Update both language versions together, preserving requirement IDs, commands, versions, and validation statuses. The main `README.md` is English; the Korean version is `README-KO.md`.

## 4. Modules

- `core/`: Pure Java, dependency-free SPI, limited SQL dialects, and policy checks — **runnable**.
- `spring-boot-demo/`: Spring Boot 3.5.16 + JPA + MyBatis + JDBC + H2 — **business sources verified programmatically in Phase 3; full Boot/Gradle execution NOT RUN**.
- `sql-jsqlparser/`: Pinned JSqlParser 5.4 validation adapter outside Core — **parser/SPI contracts passed; no SQL translation or real-DB support claim**.
- `udak-api/`: Minimal CRUD/Query contracts with per-table allowlists.
- `jdbc-spring/`: Executor participating in Spring transactions on the supplied DataSource.
- `db-testkit/`: Directly managed four-DBMS providers and owned fixtures; actual minimal functional G2 PASS.
- `observe-core/`: JDK-only non-sensitive Observe events and shape hashes.
- `legacy-observe/`: Explicit Hibernate/MyBatis/JDBC Observe adapters.
- `sql-inventory/`: JDK-only bounded capture and snapshot export for Observe.
- `tx-trace-spring/` — opt-in Spring local transaction boundaries and SQL observation correlation.
- `tx-trace-spring/`: Opt-in Spring transaction tracing for existing Observe hooks.
- `legacy-compat-testkit/`: Same-DS compatibility using existing Entity/Repository/Mapper/service.
- `consistency-core/` — JDK-only transaction diagnostics, enforcement policy and immutable reports.
- `consistency-spring/` — Explicit Spring configuration and current-thread diagnostics.
- `consistency-testkit/` — Actual Spring/H2 transaction diagnostic contracts.
- `rewrite-core/` — JDK-only approval and evidence registry and rewrite SPI.
- `rewrite-jsqlparser/` — limited SELECT paging rewrite using JSqlParser 5.4.
- `rewrite-jdbc/` — explicit Spring JDBC execution of approved rewrites.
- `rewrite-testkit/` — selective rewrite equivalence and transaction validation.
- `starter-boot3/` and `starter-boot4/` — separate Spring Boot auto-configuration with Observe defaults.
- `starter-testkit/` — isolated Gradle packaging and independent consumer application contracts.
- `tools/`: Execution scripts.
- `evidence/`: Evidence from tests that were actually run and passed.
- `docs/en/`: English documentation.
- `docs/ko/`: Korean documentation.

## 5. Environment and versions

- Java 17+; the Core can also be compiled on JDK 21 using `--release 17`.
- Phase 6 Starter targets are Spring Boot 3.5.16 / Spring Framework 6.2.19 and Spring Boot 4.1.2 / Spring Framework 7.0.10.
- MyBatis Starter 3.0.5 targets the Boot 3 line; verify its coordinates during actual Gradle dependency resolution.
- The Phase 6 harness pins Gradle 8.14.3 independently of the demo Wrapper.
- Gradle 8.14+ is recommended. Gradle Wrapper scripts, configuration, and jar are included. Gradle demo dependency resolution and full Boot execution remain unverified; Phase 3 used separately resolved public Maven dependencies.

Official references: [Spring Boot](https://docs.spring.io/spring-boot/), [MyBatis Spring Boot Starter](https://mybatis.org/spring-boot-starter/mybatis-spring-boot-autoconfigure/index.html).

## 6. Explicit limits on guarantees

UDAK does not guarantee:

- Identical behavior for every vendor-specific feature after writing SQL once.
- Automatic synchronization of the JPA first-level cache or flush behavior.
- Atomic commits across multiple databases through a single `@Transactional` annotation.
- Identical schemas, time zones, isolation levels, or execution plans.
- Safe automatic translation of unverified SQL.

These boundaries define the feature and assurance contracts needed to prevent operational incidents.

## 7. Security file exclusions

`.gitignore` and `.dockerignore` exclude credentials, private keys, cloud/infrastructure state, database dumps, network captures, and raw security scan findings. Store raw findings in `.security-local/` and share only sanitized security documents and validation evidence. Inspect index filenames separately for already tracked files and `git add -f`. These exclusions do not replace dependency vulnerability checks.
