# Feature development handoff

English | [한국어](../ko/33-FEATURE-HANDOFF.md)

## ThingsBoard CE external pilot verified

The selected independent application is ThingsBoard CE `v4.3.1.8`. The device registration success and rollback methods were verified in its pinned checkout. The previous synthetic H2 order replay remains separate evidence. [ThingsBoard pilot prerequisites](34-LEGACY-ADOPTION-PILOT.md#thingsboard-ce-external-pilot)

## Verified scope

The ThingsBoard device registration and rollback baseline and the Hibernate Observe OFF/ON comparison passed. The verified upstream COUNT replay then passed PostgreSQL assertions and PR report verification. [External pilot evidence](../../evidence/THINGSBOARD-OBSERVE-AND-SQL-CHANGE-VALIDATION.json)

The NEXT-005 hands-on review is complete. Setup took 16.368 seconds and verification, including manual confirmation, took 45.044 seconds. The operator role was self-declared. [Hands-on review evidence](../../evidence/THINGSBOARD-NEXT-005-MAINTAINER-REVIEW.json)

The same Device DAO yielded another verified SQL change in PR #14036. The report detected the added customer ID projection and mapped it to one impacted test. Three isolated PostgreSQL assertions passed, the UUID control reported zero changes, and cleanup passed. [Follow-up SQL replay evidence](../../evidence/THINGSBOARD-DEVICE-DAO-FOLLOWUP-VALIDATION.json)

NEXT-004 now links the PR #14036 device query to schema impact analysis. On isolated PostgreSQL the missing customer ID selected one registered test and replay confirmed SQLSTATE `42703`. The unused-column change selected no tests. [Device schema impact evidence](../../evidence/THINGSBOARD-DEVICE-SCHEMA-IMPACT-VALIDATION.json)

## Following task

Extend NEXT-004 cross-environment schema contract collection and comparison to PostgreSQL. Collect the selected table read-only from local and development fixtures at the same code revision. Verify `MATCH` when the columns agree and `DRIFT` when the comparison environment is missing a column. [Cross-environment schema contract](27-SCHEMA-IMPACT-REGRESSION.md#compare-schema-contracts-across-environments)

Public publication is deferred. Resume the remaining official performance and DB support checks when their documented prerequisites are met. [Release and support evidence](30-RELEASE-SUPPORT-EVIDENCE.md) · [Product G5 criteria](32-PRODUCT-G5-ACCEPTANCE.md)
