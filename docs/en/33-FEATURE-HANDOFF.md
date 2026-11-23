# Feature development handoff

English | [한국어](../ko/33-FEATURE-HANDOFF.md)

## ThingsBoard CE external pilot dependencies

The selected independent application is ThingsBoard CE `v4.3.1.8`. The device registration success and rollback methods were verified in its pinned checkout. The previous synthetic H2 order replay remains separate evidence. [ThingsBoard pilot prerequisites](34-LEGACY-ADOPTION-PILOT.md#thingsboard-ce-external-pilot)

## Verified scope

The ThingsBoard device registration and rollback baseline passed on isolated PostgreSQL 18 using the verified published DAO test JAR. Two test invocations each reported 2 tests with zero failures, errors and skips. A fresh PostgreSQL test container was observed and cleanup passed. [PostgreSQL baseline evidence](../../evidence/THINGSBOARD-DEVICE-BASELINE-VALIDATION.json)

## Following task

Attach Observe through a test-only Hibernate configuration. Run the same two methods with Observe OFF and ON against fresh PostgreSQL test instances. Compare the registration result, rollback assertions, observation coverage and connection effort. Once the comparison passes, verify that the PR report detects a reviewed upstream SQL change. [Pilot procedure](34-LEGACY-ADOPTION-PILOT.md#thingsboard-ce-external-pilot)

Public publication is deferred. Resume the remaining official performance and DB support checks when their documented prerequisites are met. [Release and support evidence](30-RELEASE-SUPPORT-EVIDENCE.md) · [Product G5 criteria](32-PRODUCT-G5-ACCEPTANCE.md)
