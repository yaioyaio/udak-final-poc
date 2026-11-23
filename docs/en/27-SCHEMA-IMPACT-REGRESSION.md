# Schema impact and per-query real-DB regression

English | [한국어](../ko/27-SCHEMA-IMPACT-REGRESSION.md)

Product expansion Phase 3 is **PASS**. `SCHEMA-001` through `SCHEMA-003` cover normalized schema comparison, the fixed-fixture real-DB regression and its bounded runner. [Traceability and verification status](16-TRACEABILITY.md)

## Compare normalized schema metadata

Provide versioned base/head schema snapshots, the Phase 1 head SQL inventory, and an explicit head query dependency manifest. Run from the repository root and use the required filenames.

```bash
python3 tools/schema-impact.py \
  --base build/schema/base/SCHEMA-SNAPSHOT.json \
  --head build/schema/head/SCHEMA-SNAPSHOT.json \
  --inventory build/schema/head/SQL-INVENTORY.json \
  --dependencies build/schema/head/QUERY-DEPENDENCIES.json
```

| Input | JSON fields |
|---|---|
| `SCHEMA-SNAPSHOT.json` (base and head) | `schema_version` (integer `1`), `revision`, `scope`, `columns`. Each column has `table`, `column`, `type`, `width` and `nullable` (boolean). |
| `SQL-INVENTORY.json` (head) | Phase 1 inventory snapshot with `schema_version`, `revision`, `profile`, `dropped` and `entries`. Each explicit query uses the stable `query_id_hash` and registered test hashes. |
| `QUERY-DEPENDENCIES.json` (head) | `schema_version` (integer `1`), `revision`, `scope`, `dependencies`. Each dependency has `framework` (`JPA`, `MYBATIS` or `JDBC`), the inventory's `query_id_hash`, and `columns` with `table` and `column` pairs. Use `*` as the `column` to cover every column change in that table. |

Base and head `revision` values must differ and consist of 40 or 64 lowercase hexadecimal characters. Both snapshots and the manifest share one `scope` of 64 lowercase hexadecimal characters. The head snapshot, inventory and manifest share the head `revision`. `query_id_hash` also uses 64 lowercase hexadecimal characters. Table and column identifiers start with a lowercase letter, followed by lowercase letters, digits or underscores, up to 63 characters in total. Normalized types are `INTEGER`, `BIGINT`, `VARCHAR`, `DECIMAL`, `BOOLEAN`, `DATE`, `TIMESTAMP` and `TEXT`. Use `width` from 1 through 100,000 for `VARCHAR` and 0 for the other types.

The CLI is read-only and uses bounded local JSON files on POSIX. Each input must be a regular file with a single hard link, at most 1 MiB, at a relative path without symlinks. A snapshot supports up to 4,096 columns and a dependency manifest up to 128 queries with up to 128 references each. The CLI accepts normalized metadata only. DDL, migration and repository source parsing are outside the implemented scope, and the CLI executes no SQL. [Phase 1 inventory contract](25-SQL-INVENTORY-PR-REPORT.md)

| Exit | Meaning |
|---|---|
| `0` | `COMPLETE`. The report provides schema changes, affected query hashes and deduplicated `impacted_test_ids` containing test hashes. Detected change kinds are `ADDED`, `REMOVED`, `TYPE`, `WIDTH` and `NULLABILITY`. |
| `1` | Invalid arguments or inputs. |
| `2` | `INCOMPLETE`. The report still includes known changes and impacts. Dropped inventory entries, unavailable observations, observation-only placeholder IDs, missing tests or dependencies, and unknown queries or references make the comparison incomplete. |


## Compare schema contracts across environments

NEXT-004 collects version-1 normalized column snapshots from an existing JDBC connection. The initial supported DBMS is H2, validated with driver 2.3.232. Supply the exact JDBC catalog and schema and map each stable logical table name to its exact physical table name. Use the same logical table set in both environments. The collector reads JDBC column metadata, leaves the caller's connection open and preserves its state. [JDBC column metadata](https://docs.oracle.com/en/java/javase/17/docs/api/java.sql/java/sql/DatabaseMetaData.html#getColumns(java.lang.String,java.lang.String,java.lang.String,java.lang.String))

```java
String snapshot = SchemaSnapshotCollector.collect(
        connection, revision, connection.getCatalog(), "PUBLIC",
        Map.of("contract_item", "CONTRACT_ITEM"));
Files.writeString(snapshotPath, snapshot, StandardOpenOption.CREATE_NEW);
```

Store the baseline and current JSON under the required filename and run the CLI from the repository root. The revision can be the same in both snapshots. The scope digest binds the DBMS and logical table set. The CLI validates both the digest and the actual table set.

```bash
python3 tools/schema-drift.py --dbms H2 --table contract_item \
  --baseline build/schema/baseline/SCHEMA-SNAPSHOT.json \
  --current build/schema/current/SCHEMA-SNAPSHOT.json
```

Exit `0` means `MATCH`, exit `2` means `DRIFT`, and exit `1` means invalid input or scope. Changes identify column additions, removals, type, VARCHAR length and nullability. Missing or inaccessible selected tables and unsupported column metadata fail capture. The bounds are 128 selected tables and 4,096 columns. The collector normalizes ordinary H2 uppercase or lowercase identifiers to lowercase and rejects mixed-case columns. The output contains logical identifiers and column definitions. Use identifiers approved for sharing. Keys, indexes, defaults, decimal precision/scale, migration history and automatic query dependency extraction are outside this contract.

Run the bounded local checks with `python3 tools/run-schema-drift.py`. The harness validates two independent H2 captures with matching metadata and a changed H2 environment at the same revision. External DBMS verification for this collector is NOT RUN. [NEXT-004 validation evidence](../../evidence/SCHEMA-DRIFT-VALIDATION.json)

## Verify schema impact on the independent order service

Reuse the verified independent order pilot checkout. The protected harness verifies its source and dependency hashes, compiles the existing application and runs H2 with isolated synthetic fixtures. It collects schema metadata and runtime inventory and creates a version-1 explicit dependency manifest. The manifest covers the observed order path with `requireActiveStock=false` and a separate JDBC audit-count test. The JDBC order entry also covers the order and stock statements seen through the shared wrapper.

```bash
python3 -B tools/run-order-schema-impact.py --pilot-root ../udak-legacy-order-service-test
```

| Observed schema change | Affected tests |
|---|---|
| `order_audit.event_code` grows from `VARCHAR(16)` to `VARCHAR(32)`. | Order placement connected to the JDBC audit write. The audit-count test only refers to the order ID. |
| `order_audit.fixture_note` grows from `VARCHAR(16)` to `VARCHAR(32)`. | Zero. The unused fixture column provides a control on the same table. |

Both comparisons returned `COMPLETE` with zero unresolved queries. The capture passed 21 assertions. The selected test ran on fresh H2 fixtures whose metadata hashes matched the compared schema and passed 26 assertions for schema checks, commit and rollback. A mismatched schema hash was rejected before replay. Seventeen schema-impact contracts and protected Core smoke passed. External DB integration is NOT RUN. [Order schema impact evidence](../../evidence/ORDER-SCHEMA-IMPACT-VALIDATION.json)

## Extract column dependencies from static SQL

Run `tools/sql-dependencies.py --schema <relative path to SCHEMA-SNAPSHOT.json>` with Python 3 and pass one static SQL statement on UTF-8 standard input, up to 16 KiB. The extractor supports `SELECT COUNT(column) FROM table` and `INSERT INTO table (columns) VALUES (?, ...)` with simple unqualified identifiers. It checks every extracted column against the supplied schema. The extractor also accepts a single-table stock UPDATE with `SET target = source - ?`, followed by `WHERE key1 = ? AND key2 = ? AND amount >= ?` and an optional `AND flag = TRUE`. It resolves both assignment columns and every predicate column against the schema.

The JSON report contains only `status`, `reason`, and sorted table/column references. Exit `0` returns `RESOLVED`. Exit `2` returns `UNRESOLVED` with `UNKNOWN_REFERENCE` for a reference absent from the schema, `DYNAMIC_SQL` for dynamic SQL markers, or `UNSUPPORTED_SQL` for constructs such as joins or ambiguous references. Exit `1` reports invalid input, arguments, or schema as a generic error.

```bash
python3 -B tools/run-order-schema-impact.py --dependency-extraction
```

The fixed order fixture checks that both static declarations, audit count and audit insert, match their exact references in the reviewed manifest. Using extraction alone fully covers the audit count entry, one of four framework/query entries. The other three remain uncovered and the impact report is `INCOMPLETE`. Combining reviewed explicit upstream references with the extracted audit insert dependency selects one order placement test for the related `event_code` change and zero tests for the unused `fixture_note` change. The guarded run passed 9 extraction contracts, 17 schema-impact contracts and 26 selected-order replay assertions. External DB integration is NOT RUN. [Order dependency extraction evidence](../../evidence/ORDER-DEPENDENCY-EXTRACTION-VALIDATION.json)

## Verify rendered order stock UPDATE dependencies

```bash
python3 -B tools/run-order-schema-impact.py --stock-update
```

| MyBatis stock path | Reviewed `order_stock` column references |
|---|---|
| Active-stock condition OFF | `available`, `sku_id`, `warehouse_id` |
| Active-stock condition ON | `active`, `available`, `sku_id`, `warehouse_id` |

The harness compares the statement prepared by MyBatis with the reviewed references for each scope. The original dynamic mapper template and an ambiguous UPDATE stay unresolved. Making `active` nullable selects only the ON test. Widening unused `fixture_note` selects zero tests. Omitting the ON dependency makes the comparison `INCOMPLETE`. The selected test is replayed on a fresh H2 fixture with matching metadata and verifies commit, rollback and rejection of inactive stock. External DB integration is NOT RUN. [Order stock UPDATE validation evidence](../../evidence/ORDER-STOCK-UPDATE-VALIDATION.json)

## Match observed schema changes to migration history

NEXT-004 provides a separate read-only comparison of version-1 schema snapshots, declared migration history and a reviewed migration manifest. Run it from the repository root with bounded local JSON inputs.

```bash
python3 -B tools/schema-migration.py \
  --base build/schema/base/SCHEMA-SNAPSHOT.json \
  --head build/schema/head/SCHEMA-SNAPSHOT.json \
  --base-history build/schema/base/MIGRATION-HISTORY.json \
  --head-history build/schema/head/MIGRATION-HISTORY.json \
  --manifest build/schema/head/MIGRATION-MANIFEST.json
```

Each history file has `schema_version` (integer `1`), `revision`, `scope` and an applied-order `migrations` array. Each row has a unique version string (`version`) and `checksum_sha256`. The manifest has `schema_version`, `base_revision`, `revision` (head), `scope`, `version`, `checksum_sha256` and `expected_changes_sha256`. All five inputs must share the exact scope and align to the distinct base and head revisions.

The base history must be an exact prefix of the head history in applied order. The head must add exactly one version that matches the manifest's version and SHA-256 of the exact reviewed migration file bytes. Compute `expected_changes_sha256` from the reviewed change array in `schema.compare_columns` order and shape using `json.dumps(changes, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")`.

Exit `0` means `MATCHED`. Exit `2` means `UNRESOLVED`, including missing or divergent history, an empty schema diff, or changes that differ from the reviewed delta. Exit `1` means invalid arguments, inputs or scope. The CLI uses declared evidence to compare history and metadata. Flyway and Liquibase import, generic DDL parsing and external causal attribution are outside its scope.

The order harness applies V002 to widen `order_audit.event_code` from `VARCHAR(16)` to `VARCHAR(32)` in isolated H2 fixtures. It reads the fixture history through JDBC and checks the reviewed change with matching history, the same change with missing history, and recorded V002 with unrelated drift after the event-code width is restored. The run returned `MATCHED`, `HISTORY_MISSING` and `CHANGE_MISMATCH` for the three cases. [Order migration history evidence](../../evidence/ORDER-MIGRATION-HISTORY-VALIDATION.json)

```bash
python3 -B tools/run-order-schema-impact.py --pilot-root ../udak-legacy-order-service-test --migration-history
```

## Reproduce the fixed-fixture regression

Use Python 3, JDK 17 or later, Maven Central access, and existing native arm64 Homebrew PostgreSQL 17 and MySQL 8.0 binaries on macOS. The runner initializes separate scratch instances, starts one at a time and uses its own fixtures. The 12 existing stopped containers are retained and the runner creates no containers. [PostgreSQL 17 initialization](https://www.postgresql.org/docs/17/app-initdb.html) · [MySQL 8.0 initialization](https://dev.mysql.com/doc/refman/8.0/en/data-directory-initialization.html)

```bash
python3 tools/run-schema-regression.py
```

The runner pins PostgreSQL JDBC 42.7.14 with checker-qual 3.55.1 and MySQL Connector/J 26.10.0 with protobuf-java 4.36.1. On each engine it creates fixtures and widens the head fixture's nullable `label` from `VARCHAR(32)` to `VARCHAR(64)`. JDBC metadata produces the snapshots that select two affected queries per engine: a lookup by bound ID and an ordered list. The ID-only ordered query checks impact selection. The runner compares base and head results with each other and with independent expected rows, checking column labels, SQL and Java types, NULL handling, ordering and the empty lookup result.

The regression covers those four query/engine pairs. SQL Server, Oracle, production schemas and performance or load tests are **NOT RUN**. G0 approval remains pending. Expansion Phase 4 covers bounded DB/driver cancellation and recovery, including connection reuse and transaction outcomes. [Expansion roadmap](09-WBS-ROADMAP.md)

The inventory `profile` must equal the schema `scope`. A changed schema with an empty inventory is incomplete.

## Actual validation results

| Actual DB | JDBC driver | Execution result |
|---|---|---|
| PostgreSQL 17.11 | PostgreSQL JDBC 42.7.14 | Two selected queries and 98 assertions PASS |
| MySQL 8.0.46 | MySQL Connector/J 26.10.0 | Two selected queries and 98 assertions PASS |

Both engines selected the same schema change and test identities and produced matching per-query result hashes. Seventeen impact contract tests, 48 Inventory assertions, and Core smoke passed. The runner starts native servers sequentially and uses only fresh fixture data. The evidence records native binary versions and hashes and JDBC-observed server and driver identities. [Execution evidence](../../evidence/SCHEMA-REGRESSION-VALIDATION.json)

Owned process groups exited after the real DB run. Cleanup removed 1,188 temporary files and 149,563,199 bytes. Separate failure and interruption probes also stopped the owned PostgreSQL server and left no scratch files. The repository check matched the IDs and stopped states of all twelve existing managed containers. [Cleanup and repository verification](../../evidence/SCHEMA-REPOSITORY-VALIDATION.json)
