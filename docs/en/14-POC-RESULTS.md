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
- jOOQ or another external Parser/Translator Provider
- SQL rewriting runtime, JPA/MyBatis/JDBC Interceptors
- Actual PostgreSQL/MySQL/SQL Server/Oracle connections and integration tests
- External SQL Engine license verification results
- SQL semantics equivalence proof/verification reports
- Boot4 Starter, CI/CD, performance benchmark

## Prohibited compatibility claims

**SQL rendering strings are not evidence of real-database behavior on the four DBMSs.**

SQL parser limitations, SQL Server ORDER BY rules, Oracle 11g syntax, and each DBMS's drivers and differences must be tested through real-database integration tests before declaring product support.
