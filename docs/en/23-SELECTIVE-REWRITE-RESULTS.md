# Phase 5 approved selective SQL rewrite results

English | [한국어](../ko/23-SELECTIVE-REWRITE-RESULTS.md)

## Status

**IN_PROGRESS / LOCAL PASS.** Four-database equivalence, full evidence verification and G4 are **NOT RUN**. The retention cap of 12, preserving 8 existing dedicated databases and adding 4 new ones for validation, awaits user authorization. Phase 5 created and started 0 new Docker containers.

| Executed check | Result |
|---|---|
| Approval policy / parser / JDBC contracts | PASS, 330 / 147 / 67 assertions |
| In-memory H2 equivalence | PASS, 323 assertions across 8 verification categories, including 7 fixed paging and null cases |
| Existing Core / parser / API / transaction policy | PASS, 74 / 83 / 313 / 123 assertions |
| Existing mixed-access H2 | PASS, 10 scenarios |
| Local evidence verification | PASS, 7 local cases out of 20. The 13 real-DB-dependent cases are NOT RUN. The default cap of 8 blocking check passed |
| Automatic temporary workspace cleanup | PASS, 251 files and 40,499,519 bytes reclaimed. Worker quiescence verified, 0 temporary directories remaining |

[Local execution evidence](../../evidence/PHASE5-VALIDATION.json) · [Local evidence verification](../../evidence/PHASE5-LOCAL-VERIFIER-VALIDATION.json)

Adding the modules changed the `settings.gradle.kts` hash. The same guarded runner revalidated and refreshed three Phase 4 evidence files. Phase 4 source and runners and the existing G3 real-DB evidence were preserved. Evidence from the initial Phase 5 preflight failure was retained in `.git/udak-phase5/previous-reports` after correction.

## Implemented contract

- The JDK-only `Rewrite` class in `rewrite-core` provides `Registry`, `Template`, `Environment`, `Approval`, `Evidence`, `Provider` and `Plan`. A trusted operator registers approvals and evidence. Test-issued approvals are not production authorization; production issuance requires a separate trusted-operator decision.
- `PaginationRewriteProvider` (`jsqlparser-5.4-subset-1`) in `rewrite-jsqlparser` accepts the exact PostgreSQL form `SELECT c1, c2 FROM t WHERE filter = ? ORDER BY c1 ASC LIMIT ? OFFSET ?`. The table and columns are allowlisted identifiers. The fixture uses a unique non-null `c1` key. Comments, extra clauses and other deviations from the canonical form are denied. PostgreSQL, MySQL and H2 targets use `LIMIT ? OFFSET ?`. SQL Server and Oracle use `OFFSET ? ROWS FETCH NEXT ? ROWS ONLY`. Bind order is filter/limit/offset and filter/offset/limit, respectively. Dialect-specific quoted `AS` aliases preserve the exact source result labels.
- The registry checks Query ID, SHA-256 of the exact UTF-8 SQL, 8 environment fields (source and target DBMS, SHA-256 of the full source and target server and target driver version strings, schema/provider/runtime versions), evidence ID/hash/checks, target SQL and the plan fingerprint covering bind order and result labels, expiry and revocation. It checks approval validity before and after translation. Revocation before the final check prevents admission. Work already admitted may finish. The harness separately attests pinned driver artifacts and images. Version fingerprints alone cannot establish the authenticity of binaries returning the same version strings. The runner distinguishes manifest identifiers from image config IDs and checks pinned inputs before and after execution.
- `SelectiveJdbcClient.query(Template, Parameters, RowMapper)` in `rewrite-jdbc` explicitly executes the rewrite. It checks JDBC metadata for the target product and server/driver versions before preparing SQL. Inputs are a filter string up to 1,024 characters or null, limit 1–1,000 and offset 0–1,000,000. It prepares a read-only SELECT, uses typed binds, validates result labels and delegates row mapping. The JDBC query timeout is 5 seconds. It participates in the existing Spring DataSource transaction. Denied calls prepare 0 statements. The client performs no source SQL fallback, automatic JPA flush/cache synchronization or transaction-manager changes. Existing JPA, MyBatis and JdbcTemplate Observe paths remain in use. UDAK sanitizes exceptions at its boundary. External JDBC, Spring and operational logging use their own configuration.
- `rewrite-testkit` checks the contract, row results and transaction boundary within this approval scope. Equivalence is limited to the fixed fixture with unique non-null integer keys, nonempty strings and null values, and active/null filters. JDBC type differences such as PostgreSQL INTEGER and Oracle NUMERIC are compared through logical int/String mapper values. General equivalence involving Oracle empty strings or MySQL collation lies outside the scope.

## Remaining validation

Reproduce local results with `python3 tools/run-phase5.py`. After retention authorization, run the real checks with `python3 tools/run-phase5-real.py --retention-cap 12`. The default cap of 8 returns NOT RUN before creating anything. The runner checks ownership and stopped state for existing managed databases and records a fresh run UUID. It starts one database at a time and stops and retains each one. On failure it stops and preserves resources and discards ephemeral credentials. For example, with the original 8 databases and 1 retained failure, a fresh run of 4 requires a cap of at least 13. Resumption requires capacity for the actual retained count or authorization for an equivalent provider.

G4 requires actual execution of the original SQL on PostgreSQL, comparison of original, translated and independently expected results across 8 categories for each of the 4 target databases (32 total), and all 20 verifier tests passing without skips. With the full evidence, run `python3 tools/verify-phase5.py` to check G4. Phase 6 follows G4.

Performance and load, general SQL and other translation directions, Boot/Gradle, XA, graceful shutdown and recovery, and production approval issuance are NOT RUN.
