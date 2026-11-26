# Database Compatibility Matrix & Dialect Policy

English | [한국어](../ko/04-DBMS-COMPATIBILITY.md)

## 1. Targets

- PostgreSQL (minimum major version to be determined after actual DB testing)
- MySQL 8.x or later candidate (to be determined after actual DB testing)
- SQL Server 2019/2022 and other candidates (to be determined after license/version testing)
- Oracle 19c or later candidate; Oracle 11g is a separate Legacy profile

**Passing SQL generation tests does not certify DBMS support.** Actual Driver, Server, Collation, Schema, and Transaction verification is required.

## 2. Basic SQL Comparison

| Feature | PostgreSQL | MySQL | SQL Server | Oracle |
|---|---|---|---|---|
| Pagination | `LIMIT/OFFSET` | `LIMIT/OFFSET` | `OFFSET...FETCH` + ORDER BY | 12c+ `OFFSET...FETCH`, 11g ROWNUM |
| Upsert | ON CONFLICT | ON DUPLICATE KEY | Separate safe strategy | MERGE, etc. |
| Identity/sequence | identity/sequence | auto_increment | identity/sequence | version-dependent |
| Boolean | BOOLEAN | Treated as TINYINT(1) alias | BIT | Version-specific types/mappings |
| JSON | JSON/JSONB | JSON | Check per feature | Check per version |
| Case/collation | Depends on DB locale | Depends on collation | Depends on collation | Depends on NLS/collation |
| Timestamp | TZ-aware / without TZ | Depends on session/type | datetimeoffset, etc. | timestamp w/ TZ, etc. |

## 3. Common SQL Support Tiers

- Tier-A: Basic comparison/conditions/inner JOIN/ORDER/BASIC PAGE
- Tier-B: LEFT JOIN, GROUP, aggregation, generated key, batch, locking
- Tier-C: CTE, window, JSON, arrays, MERGE, procedural SQL

The MVP starts actual testing with Tier-A. For B/C, specify Capabilities per feature and conditions per provider.

## 4. Semantic Differences to Watch

- `NULL` and empty strings: Oracle's empty-string handling, etc.
- timezone: `LocalDateTime` does not represent an instant
- isolation: Default isolation levels differ by database
- `LIKE`, case sensitivity, and sorting results: Depend on collation
- generated keys: Differences in identity/sequence mechanisms
- transaction DDL: Differences in automatic commit/implicit behavior by DB
- execution plans: Performance differs even with identical SQL

## 5. Separate Treatment of Oracle 11g

The POC's `ORACLE_11` ROWNUM code demonstrates SQL strings/binding order. It has not been verified against an actual 11g DB connection. Do not claim direct Oracle 11g support through recent Hibernate versions.

## 6. Verification Evidence

Fields: `dbms`, `server_version`, `driver_version`, `sql_engine`, `schema_version`, `query_id`, `sql_hash`, `input_dataset`, `output_hash`, `performance_baseline`, `test_result`.

## Fluent SELECT with JOIN (T-007)

T-007 covers explicit INNER and LEFT joins, column equality in ON, parameterized WHERE, and ordered pagination. Physical table and column identifiers come from the configured allowlist and remain unquoted. Each rendering profile quotes table aliases and result labels as follows.

| Rendering profile | Alias and label quoting | Pagination | Pagination bind order |
|---|---|---|---|
| `POSTGRESQL` | Double quotes | `LIMIT ? OFFSET ?` | limit, offset |
| `MYSQL` | Backticks | `LIMIT ? OFFSET ?` | limit, offset |
| `SQLSERVER` | Square brackets | `OFFSET ? ROWS FETCH NEXT ? ROWS ONLY` | offset, limit |
| `ORACLE_19` | Double quotes | `OFFSET ? ROWS FETCH NEXT ? ROWS ONLY` | offset, limit |
| `ORACLE_11` | Double quotes | Ordered subquery, upper `ROWNUM` bound, then outer lower bound | offset + limit, offset |

WHERE binds precede pagination binds. For a paged `ORACLE_11` query, the inner query sorts the rows before the wrapper assigns row numbers. The outer query orders by those row numbers and projects only the requested labels.

T-007 verified all five rendering profiles and execution on H2, PostgreSQL 17.11 with PgJDBC 42.7.14, and MySQL 8.0.46 with Connector/J 26.10.0. The Spring JDBC fixture covered composite joins, NULL results, filter and page bind order, and rollback. SQL Server and Oracle JOIN coverage is at the rendering level. The G2 results below cover minimal CRUD and transactions. [Real DB JOIN evidence](../../evidence/FLUENT-JOIN-REAL-DB-VALIDATION.json)

## G2 driver candidates and current decision

[Dedicated real-database G2](19-REAL-DB-G2.md) and the [manifest](../../tools/g2-dependencies.json) are the SSOT for validation pins, licenses and dedicated connections. Passing driver loading does not declare real-database support. Minimal functional G2 passed on all four real profiles; see [actual results and platform limits](20-MANAGED-G2-RESULTS.md).
