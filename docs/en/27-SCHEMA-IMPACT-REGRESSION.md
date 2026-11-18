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
