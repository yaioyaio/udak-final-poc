# Phase 5 approved selective SQL rewrite results

English | [한국어](../ko/23-SELECTIVE-REWRITE-RESULTS.md)

## Status

**G4 PASS.** Phase 5 completed implementation and validation of approved selective SQL rewrite for the fixed fixture. The original PostgreSQL SQL ran on actual PostgreSQL. Canonical result digests across all four targets matched H2. All 20 evidence verifier tests passed without skips. Production approval was not granted.

| Executed check | Result |
|---|---|
| Approval policy / parser / JDBC contracts | PASS, 330 / 147 / 67 assertions |
| In-memory H2 equivalence | PASS, 323 assertions across 8 verification categories, including 7 fixed paging and null cases |
| Existing Core / parser / API / transaction policy | PASS, 74 / 83 / 313 / 123 assertions |
| Existing mixed-access H2 | PASS, 10 scenarios |
| Full evidence verification | PASS, 20 tests, 0 skips |

| Target DBMS | Categories | Assertions | Stopped and retained container | Exit code | OOM |
|---|---:|---:|---|---:|---|
| PostgreSQL | 8 | 379 | `udak-g2-bf826cd260b74d22bda11df37f0a4b4b-postgresql` | 0 | false |
| MySQL | 8 | 323 | `udak-g2-bf826cd260b74d22bda11df37f0a4b4b-mysql` | 0 | false |
| SQL Server | 8 | 323 | `udak-g2-bf826cd260b74d22bda11df37f0a4b4b-sqlserver` | 137 | false |
| Oracle | 8 | 323 | `udak-g2-bf826cd260b74d22bda11df37f0a4b4b-oracle` | 143 | false |
| **Total** | **32** | **1,348** | | | |

[Local execution](../../evidence/PHASE5-VALIDATION.json) · [Real-DB execution](../../evidence/PHASE5-REAL-VALIDATION.json) · [Full verifier](../../evidence/PHASE5-VERIFIER-VALIDATION.json) · [G4 verdict](../../evidence/PHASE5-GATE.json) · [Container retention](../../evidence/PHASE5-CONTAINER-RETENTION.json)

Adding the modules changed the `settings.gradle.kts` hash. The same guarded runner revalidated and refreshed three Phase 4 evidence files. Phase 4 source and runners and the existing G3 real-DB evidence were preserved. Evidence from the initial Phase 5 preflight failure was retained in `.git/udak-phase5/previous-reports` after correction.

## Implemented contract

- The JDK-only `Rewrite` class in `rewrite-core` provides `Registry`, `Template`, `Environment`, `Approval`, `Evidence`, `Provider` and `Plan`. A trusted operator registers approvals and evidence. Test-issued approvals are not production authorization; production issuance requires a separate trusted-operator decision.
- `PaginationRewriteProvider` (`jsqlparser-5.4-subset-1`) in `rewrite-jsqlparser` accepts the exact PostgreSQL form `SELECT c1, c2 FROM t WHERE filter = ? ORDER BY c1 ASC LIMIT ? OFFSET ?`. The table and columns are allowlisted identifiers. The fixture uses a unique non-null `c1` key. Comments, extra clauses and other deviations from the canonical form are denied. PostgreSQL, MySQL and H2 targets use `LIMIT ? OFFSET ?`. SQL Server and Oracle use `OFFSET ? ROWS FETCH NEXT ? ROWS ONLY`. Bind order is filter/limit/offset and filter/offset/limit, respectively. Dialect-specific quoted `AS` aliases preserve the exact source result labels.
- The registry checks Query ID, SHA-256 of the exact UTF-8 SQL, 8 environment fields (source and target DBMS, SHA-256 of the full source and target server and target driver version strings, schema/provider/runtime versions), evidence ID/hash/checks, target SQL and the plan fingerprint covering bind order and result labels, expiry and revocation. It checks approval validity before and after translation. Revocation before the final check prevents admission. Work already admitted may finish. The harness separately attests pinned driver artifacts and images. Version fingerprints alone cannot establish the authenticity of binaries returning the same version strings. The runner distinguishes manifest identifiers from image config IDs and checks pinned inputs before and after execution.
- `SelectiveJdbcClient.query(Template, Parameters, RowMapper)` in `rewrite-jdbc` explicitly executes the rewrite. It checks JDBC metadata for the target product and server/driver versions before preparing SQL. Inputs are a filter string up to 1,024 characters or null, limit 1–1,000 and offset 0–1,000,000. It prepares a read-only SELECT, uses typed binds, validates result labels and delegates row mapping. The JDBC query timeout is 5 seconds. It participates in the existing Spring DataSource transaction. Denied calls prepare 0 statements. The client performs no source SQL fallback, automatic JPA flush/cache synchronization or transaction-manager changes. Existing JPA, MyBatis and JdbcTemplate Observe paths remain in use. UDAK sanitizes exceptions at its boundary. External JDBC, Spring and operational logging use their own configuration.
- `rewrite-testkit` checks the contract, row results and transaction boundary within this approval scope. Equivalence is limited to the fixed fixture with unique non-null integer keys, nonempty strings and null values, and active/null filters. JDBC type differences such as PostgreSQL INTEGER and Oracle NUMERIC are compared through logical int/String mapper values. General equivalence involving Oracle empty strings or MySQL collation lies outside the scope.

## Retention, reproduction and next phase

After the user authorized increasing the retention cap from 8 to 12, `python3 tools/run-phase5-real.py --retention-cap 12` started the four databases one at a time. The four new and eight existing instances are stopped and retained. There are 0 active managed containers. Existing resource modifications, container deletions and database volume deletions each total 0. Retained database size was not measured. SQL Server exited with code 137 and its OOM flag is false. Oracle exited with code 143. Graceful shutdown, restart recovery and native SQL Server certification are NOT RUN. G4 covers functional verification.

Automatic cleanup reclaimed 251 local files (40,499,519 bytes) and 271 real-run files (56,807,090 bytes). The total is 522 files and 97,306,609 bytes with 0 temporary directories remaining. The verifier and G4 check separately removed one owned file each (119 bytes and 64 bytes, respectively).

Run `python3 tools/run-phase5.py` to reproduce local results. Run `python3 tools/verify-phase5.py` to check existing evidence. With 12 retained instances, a fresh run of four requires separate authorization for capacity of 16 or an equivalently verified provider. The current retention authorization covers 12 instances. Resources are never deleted automatically for capacity.

The scope excludes general SQL equivalence, arbitrary data and binds, other translation directions, Oracle empty strings and MySQL collation, Boot/Gradle, XA, performance and load, and production approval issuance. Phase 6 covers separate Boot3 and Boot4 starters, CLI, local CI and formal release. GitHub Actions is prohibited. Deployment and licensing still require their own approvals.
