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

## Following task

Connect NEXT-004 PostgreSQL column snapshots to the existing migration history comparison. Use one reviewed migration in an isolated fixture. Verify `MATCHED` when the recorded version, checksum and observed column change agree, and `UNRESOLVED` when history is missing or differs. [Migration history comparison](27-SCHEMA-IMPACT-REGRESSION.md)

Public publication is deferred. Resume the remaining official performance and DB support checks when their documented prerequisites are met. [Release and support evidence](30-RELEASE-SUPPORT-EVIDENCE.md) · [Product G5 criteria](32-PRODUCT-G5-ACCEPTANCE.md)
