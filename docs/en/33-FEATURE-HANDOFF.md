# Feature development handoff

English | [한국어](../ko/33-FEATURE-HANDOFF.md)

## ThingsBoard CE external pilot source prepared

The selected independent application is ThingsBoard CE `v4.3.1.8`. The device registration success and rollback methods were verified in its pinned checkout. The previous synthetic H2 order replay remains separate evidence. [ThingsBoard pilot prerequisites](34-LEGACY-ADOPTION-PILOT.md#thingsboard-ce-external-pilot)

## Verified scope

The source pin, filtered checkout, scoped test methods and UDAK Core smoke passed. The required upstream dependency POM could not be reached and was absent from the local cache. The ThingsBoard build, isolated PostgreSQL baseline and Observe OFF/ON comparison remain NOT RUN. [ThingsBoard pilot preflight evidence](../../evidence/THINGSBOARD-DEVICE-PILOT-PREFLIGHT.json)

## Following task

Confirm that the upstream dependency resolves and that the host can run the limited DAO reactor and isolated PostgreSQL safely. Run the two existing methods as the baseline, then compare the same methods with the test-only Observe attachment.

Public publication is deferred. Resume the remaining official performance and DB support checks when their documented prerequisites are met. [Release and support evidence](30-RELEASE-SUPPORT-EVIDENCE.md) · [Product G5 criteria](32-PRODUCT-G5-ACCEPTANCE.md)
