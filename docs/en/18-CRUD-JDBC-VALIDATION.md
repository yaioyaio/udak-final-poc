# Phase 2 CRUD / JDBC Validation

English | [한국어](../ko/18-CRUD-JDBC-VALIDATION.md)

## 1. Scope and completion decision

This records minimal implementation and foundation validation for P2-API / FR-002·014 / T-006, P2-EXEC / FR-010 / T-008, P2-DB-BASE / FR-003·011 / T-009·010, and P2-HARNESS. Follow the [traceability matrix](16-TRACEABILITY.md) and [API contract](03-API-SPEC.md).

PASS in [PHASE2-VALIDATION.json](../../evidence/PHASE2-VALIDATION.json) covers the minimal API, actual Spring JDBC/H2 executor, and real-database validation foundation. **Full Phase 2 G2 is NOT PASSED**; validation against four real databases is incomplete. Existing SQL remains Observe by default with unapproved Rewrite denied.

## 2. Minimal API contract

| API | Input and result | Boundary |
|---|---|---|
| `insert` | column/value map → affected rows | Caller supplies a non-null ID |
| `updateById` | non-null ID + column/value map → affected rows | PK changes forbidden; empty changes rejected |
| `deleteById` | non-null ID → affected rows | Deletion without an ID forbidden |
| `findById` | ID + explicit `RowMapper` → `Optional<T>` | Fetches at most two rows to detect duplicates; null mapper results rejected |
| `select` | `QueryDefinition` + explicit `RowMapper` → `List<T>` | Current equality/sort/page subset |

`TableDefinition` defines a per-table column/ID allowlist and column order. Query table/column/filter/order identifiers are checked against it; values use positional binds. INSERT and UPDATE follow declared column order regardless of input map order, with the UPDATE ID bind last. Query bind order follows the compiler contract.

The SELECT path retains its default compiler and accepts an injected `SqlCompiler` through the four-argument `CrudClient` constructor. Per-table identifier checks run before the provider. INSERT/UPDATE/DELETE use the minimal contract's common DML generation path.

Input map, column-list, and result-list snapshots are shallow. Value objects are not copied. SQL NULL values can be bound, but equality is not automatically rewritten to `IS NULL`. UPSERT, generated keys, automatic ID generation, and ORM lifecycle/cache/flush are not provided.

`RowMapper` processes the current row of an open JDBC `ResultSet` through `map(row, rowNum)`. Read required values inside the mapper; do not retain or return the ResultSet or objects dependent on its lifetime. Use the actual column labels supplied by JDBC/driver; there is no automatic case conversion or DTO reflection. Distinguish SQL NULL from `getObject`/`getString` from primitive getter defaults using `wasNull()` where needed, and return a non-null row object.

## 3. Spring executor and security boundary

`SpringJdbcExecutor` uses the original externally injected `DataSource`. `DataSourceUtils.getConnection` / `doReleaseConnection` participate in the same DataSource's Spring transaction connection; Statement and ResultSet are closed, while Spring owns completion of a transaction-bound Connection. It creates no separate DataSource wrapper or private commit/rollback. [Official Spring connection management reference](https://docs.spring.io/spring-framework/reference/6.2/data-access/jdbc/connections.html).

Query timeout is 1–30 seconds and the result limit is 1–1000 rows, defaulting to 5 seconds and 1000 rows. A `maxRows + 1` sentinel detects excess rows and rejects the result rather than truncating it. The smaller of the external Spring TX remaining deadline and configured timeout applies. JDBC timeout depends on driver behavior; it is not a forced termination guarantee for connection acquisition or all network activity.

Values bind through `PreparedStatement.setObject`. Executor execution, mapping, and release failures become a fixed-message `SafeJdbcException` retaining no SQL, values, connection details, or original cause; Spring parameter helpers/exception translators that could expose values are avoided. This guarantee covers **the executor's internal paths**. It cannot control external DataSource, driver, or TransactionManager DEBUG/TRACE logging or caller mapper side effects; external logging policies must be applied separately.

Evidence covers participation in Spring commit/rollback on one DataSource, not atomic commits across DBMSs or automatic JPA flush/cache synchronization. It does not replace Boot3/Boot4 Starter support validation.

## 4. Actual validation and versions

| Validation | Actual result |
|---|---|
| Core smoke | PASS |
| Phase 1 basic/external compiler regression | PASS: 74 / 83 assertions |
| Minimal CRUD API | PASS: 313 assertions |
| Spring JDBC / H2 | PASS: CRUD, NULL, binds, commit/rollback, resource release, sensitive exception paths |
| DB foundation / H2 | PASS: 45 assertions |
| Cleanup probes | PASS: failure / timeout / signal / exception / descendant, 5 probes |
| PostgreSQL / MySQL / SQL Server / Oracle | All NOT RUN: DEDICATED_PROVIDER_REQUIRED |

Java compilation targets 17; actual runtime is the report's `java_runtime_version` (currently 21.0.13). Spring 6.2.19 / H2 2.3.232 are pinned and alignment with the Spring Boot 3.5.16 BOM was checked. Artifact checksums, POM dependency/license graphs, and notices passed; Spring uses Apache-2.0 and H2 selects MPL-2.0. This is not product distribution approval or completed license approval for new real-database drivers.

H2 demonstrates executor and fixture procedure execution. H2 compatibility mode or successful SQL rendering is not evidence of compatibility with four real databases. Gradle tasks, Spring Boot/JPA/MyBatis demo, performance/load tests, and product distribution approval are NOT RUN. Actual execution used `javac`/`java` and embedded H2; containers started, existing containers modified, and auxiliary worktrees created/removed were all 0.

## 5. Real-database foundation and preservation policy

The no-argument `RealDatabaseContractRunner` inventory makes no connection. Explicit execution requires exactly one `ServiceLoader` `RealDatabaseProvider` supplying `profile()`, `dataSource()`, and `dedicatedSchemaApproved()`. A candidate driver class must exist on the classpath and JDBC metadata product must match before the scenario runs. Candidate class/product checks are not declarations of support for actual server/driver versions. New real-database drivers are not downloaded automatically; version and license approval remain incomplete.

The scenario issues CREATE/DROP only for its owned fixture, `udak_p2_` plus 12 hex characters, within an approved dedicated schema. Cleanup follows CRUD, NULL, pagination, injection-like binds, and commit/rollback checks. Unconfirmed CREATE success produces `CREATION_UNCONFIRMED`; unconfirmed owned fixture DROP success produces `CLEANUP_UNCONFIRMED`; either forbids PASS. Preserve the identifier in results for follow-up and do not arbitrarily delete uncertain objects. Existing databases, tables, and secret configuration remain untouched.

## 6. Reproduction and next step

```bash
python3 tools/run-phase2.py
```

The Python standard-library harness follows repository Root policy and the existing Phase 1 guard. Limits are wall 180 seconds, child CPU 30 seconds, JVM heap 256MiB/metaspace 128MiB/active CPUs 2, downloads 5,000,000 bytes per file, and temporary workspace 2,000 files/128MiB. Pinned dependency retrieval is restricted to approved Maven origins and checksums.

Actual automatic cleanup is connected to success, failure, timeout, signal, exception, and surviving-child probes. The report records removal of 60 temporary files/8,479,319 bytes in the main run, with 0 directories remaining; each probe removed 1 temporary file/0 bytes. Previous failure reports are preserved before another run. Cleanup of arbitrary external commands or all Git completion events was not validated.

Next, supply four dedicated Phase 2 real-database providers/profiles, pin driver versions/licenses, execute with bounds, and assess G2 using actual results and cleanup evidence. **Enter Phase 3 after G2 passes.**

One empty diagnostic file/0 bytes from an early permission error remains separately preserved as uncertain material. The removal counts above cover the latest successful workspace; this exception is retained until ownership/inactivity is proven.
