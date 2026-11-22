# Feature development handoff

English | [한국어](../ko/33-FEATURE-HANDOFF.md)

## Verify schema change attribution from migration history

The independent H2 order pilot linked explicit query dependencies to schema changes and replayed one selected order test. The unrelated column change selected zero tests. [Order schema impact](27-SCHEMA-IMPACT-REGRESSION.md#verify-schema-impact-on-the-independent-order-service)

## Scope and acceptance

On the same order fixture, match one recorded migration to its version, checksum and the observed schema change. Verify the cases with a matching record, a missing record and an unrelated change. Leave discrepancies without sufficient evidence unresolved. [Schema contract and scope](27-SCHEMA-IMPACT-REGRESSION.md)

## Following task

Use the explicit order dependency manifest as the comparison baseline when evaluating automatic extraction. [Feature-first backlog](09-WBS-ROADMAP.md#feature-first-backlog)

Public publication is deferred. Resume the remaining official performance and DB support checks when their documented prerequisites are met. [Release and support evidence](30-RELEASE-SUPPORT-EVIDENCE.md) · [Product G5 criteria](32-PRODUCT-G5-ACCEPTANCE.md)
