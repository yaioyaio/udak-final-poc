# API / SPI Contract

English | [한국어](../ko/03-API-SPEC.md)

## 1. Usage Scenarios

### New Fluent API (target API, not yet implemented)

```java
List<UserDto> list = db.select(USER.ID, USER.NAME)
    .from(USER)
    .where(USER.STATUS.eq("ACTIVE"))
    .orderBy(USER.ID.desc())
    .limit(20)
    .fetch(UserDto.class);
```

The Simple API is provided separately as `CrudClient<T,ID>`. Rather than directly imitating JPA Entity `save()` semantics, it explicitly defines creation/update and ID generation policies.

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
| `select` | typed columns | `SelectBuilder` | Generate SQL AST |
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
