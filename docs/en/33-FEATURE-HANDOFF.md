# Feature development handoff

English | [한국어](../ko/33-FEATURE-HANDOFF.md)

## Resume with NEXT-001

- The 2026-11-21 review used `develop` at `5694c55`.
- NEXT-001 is TODO. The review compared source and retained evidence. Implementation and its regression tests are pending.
- Complete the product features, starting with safe diagnostic output and the legacy SQL inventory. [Feature-first backlog](09-WBS-ROADMAP.md#feature-first-backlog)

## Scope and acceptance

`Bind`, `CompiledQuery` and `QueryDefinition` use generated Java record string output. Formatting these records can expose the bind value, SQL text or filter value. For NEXT-001, limit their string output to safe metadata under NFR-03. [Core types](../../core/src/main/java/dev/udak/core) · [NFR-03](01-PRD.md)

- Use synthetic markers to verify that SQL text, bind names and values, and the filter value are absent from the output. Include a supplied value whose `toString()` fails if called.
- Verify the existing constructors, accessors, equality, binding order and execution contracts. Run `./tools/run-core-smoke.sh` through the repository's protected execution path and record the outcome.
- Start from the latest `develop` on a feature branch. Register the requirement and test plan in the English and Korean traceability documents before implementing. [Traceability](16-TRACEABILITY.md) · [Development guide](13-AGENT-DEVELOPMENT-GUIDE.md)

## Following task

After NEXT-001 passes, start NEXT-002 by connecting the local MyBatis Mapper XML scanner to the existing base/head PR report. Verify the agreed file, line, classification and hash output on bounded fixtures with external entities and network access disabled. The backlog holds the acceptance criteria for later tasks. [SQL inventory and PR report](25-SQL-INVENTORY-PR-REPORT.md) · [Feature-first backlog](09-WBS-ROADMAP.md#feature-first-backlog)

Public publication is deferred. Resume the remaining official performance and DB support checks when their documented prerequisites are met. [Release and support evidence](30-RELEASE-SUPPORT-EVIDENCE.md) · [Product G5 criteria](32-PRODUCT-G5-ACCEPTANCE.md)
