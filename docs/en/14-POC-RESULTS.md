# Execution Results and Verification Limits (2026-11-18)

English | [한국어](../ko/14-POC-RESULTS.md)

## Actually executed — PASS

Execution environment: OpenJDK 21, compiled with `javac --release 17`, no external dependencies.

Command:

```bash
./tools/run-core-smoke.sh
```

Result file: `evidence/core-smoke-output.txt`.

Items covered by the tests:

- PostgreSQL/MySQL LIMIT ? OFFSET ? rendering
- SQL Server/Oracle 19 OFFSET ? ROWS FETCH NEXT ? ROWS ONLY rendering
- Oracle 11 ROWNUM rendering (string demonstration only)
- SQL condition filtering and pagination bind order
- Blocking disallowed identifiers
- Blocking invalid pageSize
- Blocking approved rewriting when the SQL hash changes
- Blocking approved rewriting when the target DBMS changes
- Multiple-DataSource local atomicity policy warning (exception)

## Current validation status through Phase 4

- Compiled and tested the 4 existing Entity/Repository/Mapper/service sources from `spring-boot-demo` unchanged with actual Spring JPA, MyBatis-Spring and JdbcTemplate. Full Boot application, autoconfiguration and Gradle tasks are NOT RUN.
- Public Maven dependency resolution and pinned license/checksum checks ran. Product redistribution approval is NOT GRANTED.
- Minimal CRUD API, Spring-aware executor and four-real-DB G2 PASS. The full Fluent JOIN DSL remains unimplemented.
- JPA/MyBatis/JDBC Observe adapters and explicit same-DataSource flush/cache/commit/rollback G3 PASS. SQL rewrite runtime and semantic-equivalence proof remain unimplemented.
- Explicit transaction guard and actual Spring/H2 contracts passed (bounded T-014 scope). The new four-vendor transaction matrix is NOT RUN.
- Boot3/4 Starter certification, formal distribution and performance/load verification are NOT RUN. GitHub Actions is prohibited.

The sections below distinguish the historical execution scope from current evidence.

## Prohibited compatibility claims

**SQL rendering strings are not evidence of real-database behavior on the four DBMSs.**

SQL parser limitations, SQL Server ORDER BY rules, Oracle 11g syntax, and each DBMS's drivers and differences must be tested through real-database integration tests before declaring product support.

## Phase 1 execution verification — PASS

Reproduce with `python3 tools/run-phase1.py`. Evidence: [PHASE1-VALIDATION.json](../../evidence/PHASE1-VALIDATION.json).

- Completed the official-source jOOQ/Calcite/JSqlParser comparison and technical eligibility checks for the Apache-2.0 path of upstream `com.github.jsqlparser:jsqlparser:5.4`. This is separate from product distribution, legal or commercial-contract approval.
- Verified pinned JAR/POM SHA-512, published JAR SHA-512, bundled LICENSE hash/attribution, no direct compile/runtime dependencies, and class major 55. Because the binary contains no notice entries, the adapter includes separate META-INF LICENSE/NOTICE resources.
- Core smoke PASS, 74 basic Compiler and 83 external-parser contract assertions PASS. Actual Java 17-targeted compilation covered five rendering profiles, complete bind names/values/order, no value inlining, shallow immutability, invalid inputs, one SELECT and multiple-statement rejection.
- The initial external negative test exposed a multiple-statement gap. Statement-list parsing and an exact single-SELECT check fixed it. Earlier failure reports are preserved under `.git/udak-phase1/previous-reports/`. Independent review also strengthened shared test sources, bind-value checks and parser-decisive rejection tests.
- Execution bounded time, CPU, JVM, downloads and file/output sizes. Failure, timeout, signal, actual exception propagation and descendants surviving wrapper exit were verified; evidence records actual removed files/bytes, remnants and process-group termination. Uncertain material is preserved and the existing Core smoke trap remains intact.
- Completion covers external-engine comparison, selected-artifact license verification and SPI/parser contracts. Overall G0 product-distribution approval, four-real-DB equivalence, the Spring demo, Gradle task execution, SQL translation and performance/load verification are NOT RUN.

Next is Phase 2: minimal CRUD/Query contracts (FR-002·FR-014, T-006), the Spring-aware JDBC executor (T-008), and per-DBMS real-environment test foundations. Register test plans in both traceability documents first and preserve ORM semantics and transaction boundaries.

## Initial Phase 2 foundation history — PASS / full G2 incomplete at that time

Actual checks in [PHASE2-VALIDATION.json](../../evidence/PHASE2-VALIDATION.json) passed Core smoke, Java 17-targeted compilation, 74 basic and 83 external-parser Phase 1 regression assertions, 313 CRUD API assertions, actual Spring JDBC 6.2.19/H2 2.3.232 functional tests, 45 DB foundation assertions and five cleanup probes. See [contracts and scope](18-CRUD-JDBC-VALIDATION.md).

At the initial foundation run, PostgreSQL/MySQL/SQL Server/Oracle were all NOT RUN without dedicated approved providers. Full Phase 2 G2 is incomplete without actual server/driver version, result and transaction evidence. No new containers, Spring Boot application, Gradle tasks or real databases were started.

Initial published-checksum download and cleanup-probe failures are preserved under `.git/udak-phase2/previous-reports/`. Spring artifacts without published SHA-512 were checked using the official published SHA1 separately from the fixed SHA-512 pin. Subsequent bounded probes and all actual checks passed. One empty diagnostic file/0 bytes from the early permission error is preserved as uncertain material until ownership/inactivity is proven. This exception is separate from cleanup of the latest successful workspace.

## Latest Phase 2 and 3 completion evidence

After dedicated providers were established, 40 G2 checks across all four real DBs passed. See [G2 evidence](../../evidence/G2-REAL-VALIDATION.json) and [managed G2 results](20-MANAGED-G2-RESULTS.md). This supersedes the initial run limitations above.

Phase 3 passed 202 Observe and 188 adapter contract assertions, 74 existing Core assertions, 10 H2 scenarios and 40 across four real DBs. [G3 gate](../../evidence/PHASE3-GATE.json) and [Observe results](21-LEGACY-OBSERVE-RESULTS.md) record execution environments, observation gaps, automatic cleanup and 8 preserved stopped databases. SQL Server ran under emulation; graceful shutdown and restart recovery certification are NOT RUN.

## Phase 4 execution verification — PASS

Explicit configuration, current-thread transaction diagnostics and actual Spring/H2 contracts passed. Policy checks passed 123 assertions, Spring wiring passed 52 and the new contracts passed 205. The new contracts cover 9 Spring/H2 scenarios and 1 unknown-outcome policy case, with all 10 legacy H2 regression scenarios passing. The new four-vendor transaction matrix, Boot autoconfiguration, Gradle, Boot 3/4, XA, operational recovery and performance/load are NOT RUN. [PHASE4-GATE.json](../../evidence/PHASE4-GATE.json), [22-TRANSACTION-GUARD-RESULTS.md](22-TRANSACTION-GUARD-RESULTS.md).

Phase 5 covers selective SQL translation with default denial and validation of Query ID, exact-SQL fingerprint, environment, schema and provider versions and evidence.
