# Feature development handoff

English | [한국어](../ko/33-FEATURE-HANDOFF.md)

## Validate schema impact on the independent order pilot

The H2 adoption examples verified the difference between a successful query with an unavailable shape and a MyBatis session cache hit. [Coverage examples](34-LEGACY-ADOPTION-PILOT.md#diagnose-gaps-in-observe-coverage)

## Scope and acceptance

Continue the schema contract follow-up from NEXT-004. Reuse the independent order pilot to record explicit query-to-column dependencies and verify that a selected column change identifies the affected order tests. Check an unrelated change as a control. [Schema impact and regression](27-SCHEMA-IMPACT-REGRESSION.md)

## Following task

Use the pilot results to evaluate migration-history attribution and automatic dependency extraction. [Feature-first backlog](09-WBS-ROADMAP.md#feature-first-backlog)

Public publication is deferred. Resume the remaining official performance and DB support checks when their documented prerequisites are met. [Release and support evidence](30-RELEASE-SUPPORT-EVIDENCE.md) · [Product G5 criteria](32-PRODUCT-G5-ACCEPTANCE.md)
