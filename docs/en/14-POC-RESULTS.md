# Execution Results and Verification Limits (2026-11-17)

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

## Source provided — NOT RUN

- `spring-boot-demo`: Spring Boot 3.5.16 / JPA / MyBatis / JdbcTemplate / H2.
- Build/execution could not be performed because Gradle was not installed and no network environment with Maven Central access was available.
- Therefore, no claims are made about Spring Boot demo compilation, Spring context startup, or @Transactional test results.

## Not implemented — NOT IMPLEMENTED

- The complete new public Fluent DSL, CRUD executor
- SQL dialect Translator Provider and jOOQ integration (the Phase 1 parser-validation provider is implemented)
- SQL rewriting runtime, JPA/MyBatis/JDBC Interceptors
- Actual PostgreSQL/MySQL/SQL Server/Oracle connections and integration tests
- External SQL Engine license verification results
- SQL semantics equivalence proof/verification reports
- Boot4 Starter, CI/CD, performance benchmark

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

## Phase 2 requested foundation verification — PASS / full G2 incomplete

Actual checks in [PHASE2-VALIDATION.json](../../evidence/PHASE2-VALIDATION.json) passed Core smoke, Java 17-targeted compilation, 74 basic and 83 external-parser Phase 1 regression assertions, 313 CRUD API assertions, actual Spring JDBC 6.2.19/H2 2.3.232 functional tests, 45 DB foundation assertions and five cleanup probes. See [contracts and scope](18-CRUD-JDBC-VALIDATION.md).

PostgreSQL/MySQL/SQL Server/Oracle are all NOT RUN without dedicated approved providers. Full Phase 2 G2 is incomplete without actual server/driver version, result and transaction evidence. No new containers, Spring Boot application, Gradle tasks or real databases were started.

Initial published-checksum download and cleanup-probe failures are preserved under `.git/udak-phase2/previous-reports/`. Spring artifacts without published SHA-512 were checked using the official published SHA1 separately from the fixed SHA-512 pin. Subsequent bounded probes and all actual checks passed. One empty diagnostic file/0 bytes from the early permission error is preserved as uncertain material until ownership/inactivity is proven. This exception is separate from cleanup of the latest successful workspace.
