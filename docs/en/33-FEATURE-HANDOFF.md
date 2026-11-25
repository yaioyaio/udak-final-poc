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

## Following task

`OBSERVE-PG-BASELINE-AA-01` passed Java 17 target compilation and H2 A/B. Across five resumed observations, zero of 595 samples reached 90% CPU idle. The latest maximum was 78.67%. Live PostgreSQL A/A is NOT RUN, and the existing one-run approval remains available. When competing host work has subsided and preflight passes, use the same approval to verify 80 starts and 32 measured pairs. Confirm repeatability before official PostgreSQL and MySQL +5% acceptance. Oracle preflight follows both DBs passing. [Latest host observation](../../evidence/PRODUCT-G5-OBSERVE-PG-BASELINE-AA-01-RESUME-20261125T104924Z.json)
