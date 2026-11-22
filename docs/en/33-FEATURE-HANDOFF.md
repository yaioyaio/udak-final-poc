# Feature development handoff

English | [한국어](../ko/33-FEATURE-HANDOFF.md)

## Evaluate automatic query dependency extraction

The independent H2 order fixture matched one migration to its recorded version, file checksum and observed change. The same change without history and an unrelated observed change remained unresolved. [Migration and schema impact](27-SCHEMA-IMPACT-REGRESSION.md)

## Scope and acceptance

Use the verified order query-to-column manifest as the reference. Start with a static query from the fixture and compare extracted table and column references with its explicit references. Keep dynamic SQL and ambiguous references visible as unresolved. Recheck affected-test selection with the relevant-column and unused-column controls. [Order schema regression](27-SCHEMA-IMPACT-REGRESSION.md#verify-schema-impact-on-the-independent-order-service)

## Following task

Use the measured agreement and unresolved cases to determine which SQL forms should be supported. [Feature-first backlog](09-WBS-ROADMAP.md#feature-first-backlog)

Public publication is deferred. Resume the remaining official performance and DB support checks when their documented prerequisites are met. [Release and support evidence](30-RELEASE-SUPPORT-EVIDENCE.md) · [Product G5 criteria](32-PRODUCT-G5-ACCEPTANCE.md)
