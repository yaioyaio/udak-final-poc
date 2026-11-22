# Feature development handoff

English | [한국어](../ko/33-FEATURE-HANDOFF.md)

## Resume with NEXT-002

- The 2026-11-21 review used `develop` at `5694c55`.
- NEXT-001 passed protected Core smoke on 2026-11-22. NEXT-002 is TODO.
- Complete the product features, starting with safe diagnostic output and the legacy SQL inventory. [Feature-first backlog](09-WBS-ROADMAP.md#feature-first-backlog)

## Scope and acceptance

Connect a scanner for explicitly selected local MyBatis Mapper XML to the existing base/head PR report. Verify addition, change, dynamic substitution and unsupported cases using bounded fixtures. [SQL inventory and PR report](25-SQL-INVENTORY-PR-REPORT.md)

- Verify file, line, classification and hash output. Disable external entities and network access.
- Keep the existing inventory comparison contract and run its regression checks and protected Core smoke.
- Start from the latest `develop` on a feature branch. Register the requirement and test plan in the English and Korean traceability documents before implementing. [Traceability](16-TRACEABILITY.md) · [Development guide](13-AGENT-DEVELOPMENT-GUIDE.md)

## Following task

After NEXT-002 passes, start NEXT-003 with explicit composition that preserves an existing Hibernate inspector. [Feature-first backlog](09-WBS-ROADMAP.md#feature-first-backlog)

Public publication is deferred. Resume the remaining official performance and DB support checks when their documented prerequisites are met. [Release and support evidence](30-RELEASE-SUPPORT-EVIDENCE.md) · [Product G5 criteria](32-PRODUCT-G5-ACCEPTANCE.md)
