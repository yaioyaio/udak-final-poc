# Feature development handoff

English | [한국어](../ko/33-FEATURE-HANDOFF.md)

## ThingsBoard CE external pilot verified

The selected independent application is ThingsBoard CE `v4.3.1.8`. The device registration success and rollback methods were verified in its pinned checkout. The previous synthetic H2 order replay remains separate evidence. [ThingsBoard pilot prerequisites](34-LEGACY-ADOPTION-PILOT.md#thingsboard-ce-external-pilot)

## Verified scope

The ThingsBoard device registration and rollback baseline and the Hibernate Observe OFF/ON comparison passed. The verified upstream COUNT replay then passed PostgreSQL assertions and PR report verification. [External pilot evidence](../../evidence/THINGSBOARD-OBSERVE-AND-SQL-CHANGE-VALIDATION.json)

The NEXT-005 hands-on review is complete. Setup took 16.368 seconds and verification, including manual confirmation, took 45.044 seconds. The operator role was self-declared. [Hands-on review evidence](../../evidence/THINGSBOARD-NEXT-005-MAINTAINER-REVIEW.json)

The same Device DAO yielded another verified SQL change in PR #14036. The report detected the added customer ID projection and mapped it to one impacted test. Three isolated PostgreSQL assertions passed, the UUID control reported zero changes, and cleanup passed. [Follow-up SQL replay evidence](../../evidence/THINGSBOARD-DEVICE-DAO-FOLLOWUP-VALIDATION.json)

NEXT-004 now links the PR #14036 device query to schema impact analysis. On isolated PostgreSQL the missing customer ID selected one registered test and replay confirmed SQLSTATE `42703`. The unused-column change selected no tests. [Device schema impact evidence](../../evidence/THINGSBOARD-DEVICE-SCHEMA-IMPACT-VALIDATION.json)

NEXT-004 now supports cross-environment collection and comparison for PostgreSQL. Read-only collection from local and development fixtures at the same revision returned `MATCH` for equivalent columns and `DRIFT` with one removal when `customer_id` was missing. [PostgreSQL verification evidence](../../evidence/POSTGRESQL-SCHEMA-DRIFT-VALIDATION.json)

NEXT-004 now compares PostgreSQL snapshots with migration history. The reviewed version, checksum and column change returned `MATCHED` when they agreed. Missing history, different versions or checksums, and an additional column change each returned `UNRESOLVED`. [PostgreSQL migration verification evidence](../../evidence/POSTGRESQL-SCHEMA-MIGRATION-VALIDATION.json)

The isolated PostgreSQL pilot collected the actual Flyway V002 history through read-only access. It exported the row when the reviewed file matched apply-time evidence. Missing history returned `HISTORY_MISSING`. Missing apply-time evidence or a different SHA-256 blocked the export. [Flyway history verification evidence](../../evidence/POSTGRESQL-FLYWAY-HISTORY-VALIDATION.json)

The optional PR report shows the Flyway verdict and one registered test for the same `device.customer_id` removal. Missing history and unverified file evidence preserve their reasons and the test candidate and return exit code 2. [Integrated PR report evidence](../../evidence/POSTGRESQL-FLYWAY-PR-SCHEMA-REVIEW-VALIDATION.json)

`run-sql-inventory.py --pr-report` now carries the optional schema review through the guarded local path. Its output and exit codes matched the direct CLI for all four Flyway cases and SQL-only calls. [Guarded local PR verification evidence](../../evidence/GUARDED-LOCAL-PR-SCHEMA-REVIEW-VALIDATION.json)

The guarded PR report selected one registered ThingsBoard device replay. After verifying the isolated PostgreSQL target schema hash, the replay reproduced `42703`. Unresolved history, an unregistered hash and a schema mismatch blocked the target query. [Registered replay verification evidence](../../evidence/GUARDED-PR-REGISTERED-REPLAY-VALIDATION.json)

The guarded PR report compares the base report, registered test, and execution target schema hashes before showing the replay verdict in JSON and Markdown. Both formats showed `VERIFIED` and replay result `PASS` for the isolated PostgreSQL ThingsBoard query. Missing or invalid receipts, mismatched hashes and incomplete reports showed `UNVERIFIED`. [Replay verdict evidence](../../evidence/GUARDED-PR-REPLAY-VERDICT-VALIDATION.json)

NEXT-004 now collects MySQL 8.0 column contracts and uses the same comparison CLI. One isolated MySQL 8.0.46 fixture passed 27 assertions, MATCH, five DRIFT kinds, cross-DBMS scope rejection and cleanup. [MySQL evidence](../../evidence/MYSQL-SCHEMA-DRIFT-VALIDATION.json)

NEXT-004 MySQL Flyway history is linked to the existing guarded PR report. Isolated MySQL verified 61 assertions across matching, missing, checksum mismatch and unverified proof cases. PostgreSQL Flyway PR regression passed 25 assertions. [MySQL Flyway evidence](../../evidence/MYSQL-FLYWAY-HISTORY-VALIDATION.json)

T-007 Fluent JOIN passed 52 API and rendering assertions and 11 assertions each on Spring JDBC/H2, PostgreSQL and MySQL. The live fixtures verified composite joins, NULL results, binds and pagination, same-transaction visibility and rollback, and cleanup. [T-007 real DB evidence](../../evidence/FLUENT-JOIN-REAL-DB-VALIDATION.json)

T-001 defines five customer workflows, their controls and measurable criteria. The paired documents and stored technical evidence passed review. Direct customer demand remains unconfirmed. Start field validation with one approved maintenance team and one agreed workflow. [Scenario evidence](../../evidence/T-001-CUSTOMER-SCENARIO-VALIDATION.json)

The local T-001-S2 paired review passed on embedded H2 and isolated PostgreSQL. Git diff and UDAK both found the COUNT change, recorded zero false positives for the UUID control and selected the same registered replay test. Customer-run comparison is NOT RUN. [Local proxy evidence](../../evidence/T-001-LOCAL-PAIRED-REVIEW.json) · [Paired procedure](34-LEGACY-ADOPTION-PILOT.md#t-001-paired-maintainer-review) · [PostgreSQL local proxy evidence](../../evidence/T-001-LOCAL-PAIRED-REVIEW-POSTGRESQL.json)

One independent local T-001-S2 reviewer inspected Git diff and the guarded UDAK PR reports in sequence and agreed on both case verdicts and the registered regression test. External team approval remains unverified and customer-run comparison is NOT RUN. [Local reviewer evidence](../../evidence/T-001-LOCAL-OPERATOR-PAIRED-REVIEW.json)

RELEASE-021 passed the local six-module bundle rehearsal. It verified 30 artifacts, the pinned dependency graph, test signatures for the ZIP and manifest, and cleanup. [Full rehearsal evidence](../../evidence/RELEASE-READINESS-LOCAL.json)

The current RELEASE-021 private G6 and guarded local CI passed. The independent publication gate returns `VERIFIED_EVIDENCE`. [Guarded local CI](../../evidence/PHASE6-CURRENT-LOCAL-CI.json) · [Private G6](../../evidence/PHASE6-CURRENT-GATE.json) · [Independent publication check](../../evidence/PHASE6-CURRENT-PUBLICATION-CHECK.json)

## Following task

T-001 local proxy verification is complete. The customer-run comparison is closed for this local scope as **NOT RUN**. The next product task is to compare one actual review workflow with an approved maintenance team and address any observed coverage gap or review difficulty. Until a team is available, fix defects already reproduced in the core workflows. [T-001 decision and procedure](34-LEGACY-ADOPTION-PILOT.md#t-001-local-comparison-findings)

Review records from an approved team remain pending. The guarded local PR report incorrectly grouped MyBatis and JDBC changes using a common test of an unchanged fingerprint. The fix groups two v2 inventories only when a common test observed all four replaced fingerprints. Customer review timing and adoption benefits are **NOT RUN**. [PR report grouping rules](25-SQL-INVENTORY-PR-REPORT.md#review-a-shape-change-observed-by-mybatis-and-jdbc)

The independent local comparison on ThingsBoard PR #14036 used the UDAK report to confirm the observed control outcome. The adoption guide now documents how to look up the impacted test reference. This local case is complete. Resume comparison when an approved team's existing review procedure and actual review records are available. [Independent review results](34-LEGACY-ADOPTION-PILOT.md#independent-review-of-a-separate-public-pr)

### Remaining release verification

Defer official G5 reruns and remaining database support checks to the release stage.

Prioritize fingerprinting, which accounts for 704 B/op (71.5%) of the 984 B/op measured on a cache miss. First review temporary objects from string concatenation and UTF-8 encoding for the implicit Query ID hash input. Verify existing fingerprints, Query IDs and regression tests before comparing with the same DB-free harness. [Allocation measurement evidence](../../evidence/OBSERVE-L1-JDBC-ALLOCATION-ATTRIBUTION-01-RESULT.json)

On 2026-11-28, the local product G5 review passed Core smoke and 72 offline tests. The live functional refresh was **NOT RUN** at memory pressure level 2. Next, refresh the 16 PostgreSQL and MySQL and seven retained Oracle functional checks when memory pressure is normal. The 2026-11-27 schedule for `OBSERVE-PG-BASELINE-AA-01` ended, and its prior approval hash differs from the current inputs. Run the newly approved A/A on current inputs, followed by separately approved official +5% acceptance on both databases. Oracle instance preflight follows both databases passing. Native SQL Server is excluded locally. [Local verification record](../../evidence/PRODUCT-G5-LOCAL-SCOPE-20261128.json) · [Prior schedule record](../../evidence/OBSERVE-PG-BASELINE-AA-01-LOCAL-SCHEDULE.json)
