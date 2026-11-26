# API / SPI Contract

English | [한국어](../ko/03-API-SPEC.md)

## 1. Usage Scenarios

### Fluent SELECT with JOIN (T-007)

```java
var db = new SelectClient(vendor, executor, List.of(
    new TableDefinition("users", List.of("id", "name", "department_id", "status"), "id"),
    new TableDefinition("departments", List.of("id", "name"), "id")));
var user = db.table("users", "u");
var department = db.table("departments", "d");

record UserDepartment(String userName, String departmentName) {}
List<UserDepartment> rows = db
    .select(user.column("name").as("user_name"), department.column("name").as("department_name"))
    .from(user)
    .innerJoin(department, user.column("department_id").equalTo(department.column("id")))
    .whereEqual(user.column("status"), "ACTIVE")
    .orderBy(user.column("id"), false)
    .page(20, 0)
    .fetch((row, rowNum) -> new UserDepartment(
        row.getString("user_name"), row.getString("department_name")));
```

- Construct `SelectClient(DbVendor vendor, SqlExecutor executor, List<TableDefinition> tables)` with an explicit allowlist of physical tables and their columns. The client retains this allowlist for all queries. Obtain qualified column references with `table(name, alias).column(name)`. Physical table and column identifiers are validated and rendered unquoted. Table aliases and output labels use vendor-specific quoting.
- `innerJoin` and `leftJoin` accept one or more column equalities joined by `AND`. Each equality connects the new table reference to one already in scope. Joins can be chained and a table can join itself with distinct aliases. Table aliases must be unique within the query. Use `as(label)` when projected columns would otherwise share an output label.
- `whereEqual(column, value)` binds a non-null value and `whereIsNull(column)` emits `IS NULL`. Multiple filters are combined with `AND`.
- `orderBy(column, descending)` uses `false` for ascending and `true` for descending. `page(limit, offset)` requires an explicit sort and appends configured ID columns as ascending tie-breakers when they are absent from the sort. Each configured ID must uniquely identify a row in its table.
- `fetch(RowMapper<T> mapper)` returns `List<T>` through the configured executor and uses the same caller-supplied `RowMapper` contract as `CrudClient`. The mapper can read values by their output labels.

`CrudClient` provides the Simple API separately with explicit create, update, and ID policies.

Table aliases and result labels have a 30-byte ASCII limit and must be unique within their respective scopes without regard to case. The row-number label `udak_rn` is reserved. Page sizes are 1–1,000 and offsets are nonnegative. The Oracle 11g profile rejects offset and limit combinations that overflow a signed long.

See [rendering profiles and execution scope](04-DBMS-COMPATIBILITY.md#fluent-select-with-join-t-007).

Run `python3 -B tools/run-fluent-join.py` for the guarded functional checks. [Fluent JOIN evidence](../../evidence/FLUENT-JOIN-VALIDATION.json)

### Existing Compatibility (target)

```java
userJpaRepository.findById(id);
userMapper.selectById(id);
jdbcTemplate.queryForObject(sql, mapper, id);
```

These calls remain unchanged by default.

## 2. SPIs Actually Implemented in the Current Core

| Type | Purpose | Implementation Level |
|---|---|---|
| `SqlCompiler` | QueryDefinition → CompiledQuery | Implemented |
| `BasicSqlCompiler` | Generate common subset SQL | Implemented (POC only) |
| `DbVendor` | Five vendors/profiles | Implemented |
| `QueryDefinition` | SELECT with equality/sort/page | Implemented |
| `CompiledQuery` | SQL+ordered binds+vendor | Implemented |
| `ApprovedRewriteGuard` | Check approval for exact SQL hash+ID+source/target+revision | Implemented (no actual conversion) |
| `ConsistencyGuard` | Validate single local DataSource policy | Implemented (static configuration checks) |

### Current Java SPI Code

```java
public interface SqlCompiler {
    CompiledQuery compile(QueryDefinition query, DbVendor vendor);
}
public record CompiledQuery(String sql, List<Bind> binds, DbVendor vendor) {}
```

`BasicSqlCompiler` does not provide a free-form SQL parser. An explicit Allowlist is required for tables/columns.

## 3. Proposed Target Public API

| API | Input | Return | Caution |
|---|---|---|---|
| `findById` | Table/ID | `Optional<T>` | Clarify ID policy |
| `select` | typed columns | `SelectBuilder` | Current `SelectClient` supports the T-007 subset in section 1 |
| `insertInto` | typed table | `InsertBuilder` | Generated keys differ by DB |
| `update` | typed table | `UpdateBuilder` | Block missing WHERE by default |
| `deleteFrom` | typed table | `DeleteBuilder` | Block missing WHERE by default |
| `nativeSql` | SQL + binds | `NativeQuery` | No conversion by default |
| `fetchPage` | request + sort | `PageResult<T>` | Requires deterministic ORDER BY |

## 4. Query Compiler/Translator Distinction

`SqlCompiler` renders a new internal AST. `SqlTranslator` parses+rewrites existing source SQL. Do not combine the two into one interface.

The target `CompiledQuery` contains SQL text, positional binding descriptors, expected result columns, SQL/dialect version, and capabilities information. Do not store user binding **values** in the plan cache.

## 5. SQL Fingerprint/Approval Contract

Approval key: Query ID + SQL exact bytes/hash + source/target dialect/profile + schema version + provider version + approval revision + verified evidence ID.

The current POC implements only a subset (`queryId`, exact SQL hash, source/target, reviewRevision). The remainder must be added for productization.

## 6. Exception Design (target)

- `UdakCompileException`
- `UnsupportedDialectFeatureException`
- `UnapprovedRewriteException`
- `QueryContractMismatchException`
- `ConsistencyConfigurationException`

Exceptions do not include sensitive SQL binding values in their default messages.

## 7. Compiler contract verified in Phase 1

- Reject null query/vendor, invalid identifiers and pagination ranges. Apply the allowlist to every table/column/order identifier and never inline user values into SQL. A null filter value remains a bind; SQL NULL comparison semantics are not automatically rewritten.
- Input column and output bind lists are shallow immutable snapshots. Bind value objects are not deep copied. Equal inputs must produce deterministic SQL, vendor, and ordered bind names/values.
- `JSqlParserValidatingCompiler` in `sql-jsqlparser` validates basic compiler output with the upstream JSqlParser 5.4 statement-list parser and accepts exactly one SELECT. It does not rewrite SQL/binds or expose external parser types through Core.
- SQL length is capped at 16,384 characters, with one shared daemon worker, one queued task, and a 1-second timeout per parse attempt. Internal retries and cooperative cancellation mean neither a total 1-second call deadline nor forced thread termination is guaranteed. Saturation/errors fail closed; exceptions retain no SQL, values or causes.
- Run the same `CompilerContractTest` against the basic and external implementations. See [Phase 1 results](14-POC-RESULTS.md) for actual evidence and reproduction commands. Parsing success does not prove real-DB execution, result equivalence or translation of existing SQL.

## 8. Phase 2 minimal CRUD / JDBC contract

`udak-api` uses only the JDK and Core. `CrudClient` builds INSERT/UPDATE/DELETE and existing equality/sort/page SELECT statements using the per-table allowlist and declared column order of `TableDefinition(table, columns, idColumn)`. All values are binds; callers provide insert IDs. Reject writes without an ID, PK changes, disallowed identifiers and empty changes. Generated keys, UPSERT and the full Fluent DSL are out of scope.

`RowMapper<T>.map(ResultSet, rowNum)` reads an open row and returns a non-null object. JDBC labels, SQL NULL and primitive getter semantics remain explicit. `findById` inspects up to two rows to reject duplicates; list snapshots are shallow.

The `jdbc-spring` executor uses the original DataSource's Spring transaction binding and does not commit/rollback itself. It applies timeout limits of 1~30 seconds and row limits of 1~1000 with overflow detection. This is a trusted `CompiledQuery` boundary, not a SQL firewall. Internal execution/release exceptions are sanitized; external driver/DataSource/TransactionManager logs are outside its control.

See [CRUD/JDBC validation](18-CRUD-JDBC-VALIDATION.md) for the API and initial foundation tests, when the four real DBs were NOT RUN and G2 was incomplete. Subsequent dedicated-provider execution passed [actual G2](20-MANAGED-G2-RESULTS.md).

## 9. Implemented Observe contract (Phase 3)

`observe-core` is JDK-only. `SqlObserver.observe(Framework, ObservationPoint, queryId, sql)` delivers an immutable `SqlObservation` to a synchronous `ObservationSink`. Events contain only framework, point, queryIdHash, fingerprintHash, statementKind and fingerprintStatus, with no original SQL, values, connection details or exceptions.

| Boundary | Implemented contract |
|---|---|
| Fingerprint | Maximum SQL 16,384 characters and ID 256; conservative lexical shape hash; ambiguous/unsupported input uses a fixed UNAVAILABLE hash |
| Approval | Preserve exact-SQL `SqlFingerprint.sha256`; Observe hashes are not approval keys |
| Hibernate | StatementInspector returns the original input String |
| MyBatis | Observe the latest intercepted query 4/6 or update ID and already resolved BoundSql at prepare; preserve cache keys/arguments/ResultMap |
| JDBC | Explicit shared ObserveDataSource observes execute attempts; delegate ResultSet/RowMapper and resource behavior |
| Listener | Synchronous, thread-safe/nonblocking receiver responsibility; isolate nonfatal failures, preserve interruption, propagate VM/ThreadDeath |

Supply the same wrapper DataSource to EntityManagerFactory, JpaTransactionManager, MyBatis and JdbcTemplate. The original owner manages the underlying DataSource/pool lifecycle. Cursor/internal nested IDs, vendor unwrap/builders, ResultSet/metadata reverse references and plain Statement batch SQL have observation gaps. Follow [precise scope and validation](21-LEGACY-OBSERVE-RESULTS.md).

## 10. Explicit transaction diagnostics (Phase 4)

`dev.udak.consistency.TransactionGuard` defines enum-only Intent/Snapshot/Report contracts; `dev.udak.consistency.spring.SpringConsistencyGuard` checks supplied configuration and current-thread holders. `inspectConfiguration` and `inspectTransaction` report risks; explicit `requireAllowed()` blocks ERRORs. See [wiring, boundaries and verification status](22-TRANSACTION-GUARD-RESULTS.md). The existing Core static guard and exact approval hashes remain unchanged.

## 11. Explicit selective rewrite API (Phase 5)

An operator registers `Approval` and `Evidence` in `Rewrite.Registry` and wires it and `PaginationRewriteProvider` into `SelectiveJdbcClient(DataSource, Environment, Registry, Provider)`. `query(Template, Parameters, RowMapper)` executes only a `Plan` bound to the exact SQL and environment. `Parameters(filter, limit, offset)` accepts a string up to 1,024 characters or null, 1–1,000, and 0–1,000,000, respectively. The JDBC query timeout is 5 seconds. Admission denials surface as `Rewrite.Denied` and sanitized execution failures as `SelectiveJdbcClient.SafeJdbcException`. Local contracts and real-DB equivalence for the fixed fixture passed. [Phase 5 results](23-SELECTIVE-REWRITE-RESULTS.md)
