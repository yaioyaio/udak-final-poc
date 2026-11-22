# Feature development handoff

English | [한국어](../ko/33-FEATURE-HANDOFF.md)

## Start NEXT-004

NEXT-001 through NEXT-003 passed their scoped checks, including Hibernate composition and `UNAVAILABLE` reason counts. [Traceability](16-TRACEABILITY.md)

## Scope and acceptance

Collect column type, length and nullability from an explicit table list using JDBC metadata. Compare validated snapshots of two environments running the same DBMS and verify each supported change kind. Register the requirement and test plan before implementation. [Development guide](13-AGENT-DEVELOPMENT-GUIDE.md)

## Following task

After NEXT-004 passes, start NEXT-005 adoption support and value validation. [Feature-first backlog](09-WBS-ROADMAP.md#feature-first-backlog)

Public publication is deferred. Resume the remaining official performance and DB support checks when their documented prerequisites are met. [Release and support evidence](30-RELEASE-SUPPORT-EVIDENCE.md) · [Product G5 criteria](32-PRODUCT-G5-ACCEPTANCE.md)
