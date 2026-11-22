# Feature development handoff

English | [한국어](../ko/33-FEATURE-HANDOFF.md)

## Resume with NEXT-003

- The 2026-11-21 review used `develop` at `5694c55`.
- NEXT-001 and NEXT-002 passed their scoped checks on 2026-11-22. NEXT-003 is TODO. [Traceability](16-TRACEABILITY.md)
- Complete the product features, starting with safe diagnostic output and the legacy SQL inventory. [Feature-first backlog](09-WBS-ROADMAP.md#feature-first-backlog)

## Scope and acceptance

Add explicit composition that preserves an application's existing Hibernate `StatementInspector` and observes the effective SQL. Start with the existing legacy compatibility fixture. [Legacy Observe validation](21-LEGACY-OBSERVE-RESULTS.md)

- Compare Observe OFF and ON for the inspector's behavior, application results, rollback and observation events.
- Verify the existing adapter contracts and protected Core smoke.
- Start from the latest `develop` on a feature branch. Register the requirement and test plan in the English and Korean traceability documents before implementing. [Traceability](16-TRACEABILITY.md) · [Development guide](13-AGENT-DEVELOPMENT-GUIDE.md)

## Following task

After the Hibernate composition passes, add safe `UNAVAILABLE` reason counts within NEXT-003. The next backlog group is NEXT-004 schema contract and environment drift. [Feature-first backlog](09-WBS-ROADMAP.md#feature-first-backlog)

Public publication is deferred. Resume the remaining official performance and DB support checks when their documented prerequisites are met. [Release and support evidence](30-RELEASE-SUPPORT-EVIDENCE.md) · [Product G5 criteria](32-PRODUCT-G5-ACCEPTANCE.md)
