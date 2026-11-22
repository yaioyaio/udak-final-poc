# Feature development handoff

English | [한국어](../ko/33-FEATURE-HANDOFF.md)

## Resume the remainder of NEXT-003

- The 2026-11-21 review used `develop` at `5694c55`.
- NEXT-001 and NEXT-002 passed their scoped checks. The NEXT-003 Hibernate composition passed H2 verification on 2026-11-22. Reason counts remain TODO. [Traceability](16-TRACEABILITY.md)
- Complete the product features, starting with safe diagnostic output and the legacy SQL inventory. [Feature-first backlog](09-WBS-ROADMAP.md#feature-first-backlog)

## Scope and acceptance

Add safe reason codes and counts for `UNAVAILABLE` observations to identify dialect coverage gaps. The Hibernate composition already preserves the existing inspector and observes the effective SQL. [Legacy Observe validation](21-LEGACY-OBSERVE-RESULTS.md)

- Verify fixed reason codes and counts with synthetic cases. Preserve the existing fingerprints and unavailable-event semantics.
- Verify inventory compatibility and run protected Core smoke.
- Start from the latest `develop` on a feature branch. Register the requirement and test plan in the English and Korean traceability documents before implementing. [Traceability](16-TRACEABILITY.md) · [Development guide](13-AGENT-DEVELOPMENT-GUIDE.md)

## Following task

After the NEXT-003 reason counts pass, start NEXT-004 for schema contracts and environment drift. [Feature-first backlog](09-WBS-ROADMAP.md#feature-first-backlog)

Public publication is deferred. Resume the remaining official performance and DB support checks when their documented prerequisites are met. [Release and support evidence](30-RELEASE-SUPPORT-EVIDENCE.md) · [Product G5 criteria](32-PRODUCT-G5-ACCEPTANCE.md)
