# UDAK Final Decisions (2026-11-17)

English | [한국어](../ko/00-EXECUTIVE-DECISIONS.md)

## Product Identity

UDAK is a **Spring Boot Data Access Compatibility & Modernization Kit**. It is not a general-purpose ORM replacement. It optionally provides a new unified API, while its core purpose is to **discover, analyze, verify, and make limited improvements to** SQL, transaction, and DBMS differences in existing JPA/MyBatis/JdbcTemplate projects.

## Why Build It

| Existing Tool | Strengths | UDAK Opportunity |
|---|---|---|
| JPA/Hibernate | Object persistence, transactions | Analyze flush/cache/data source risks when frameworks are mixed |
| MyBatis | SQL control, Mapper XML | Inventory and track changes to SQL spread across multiple DBMSs |
| Spring JdbcTemplate | Reliable JDBC execution | Integrate SQL policy, audit, and compatibility checks |
| jOOQ | Type-safe DSL, Dialect | Unified analysis/approval system for the three legacy frameworks |

## Product Priorities

1. **Legacy Observe/Analyze** — Minimize impact on existing source code
2. **Transaction & Consistency Guard** — Prevent mistakes. Do not claim to guarantee reliability
3. **Verified Rewrite** — Allowlist / evidence-based / blocked by default
4. **Simple & Fluent New API** — Adopt when needed
5. CLI / CI / IDE / MCP — Extensions

## Explicit Non-goals

- Automatic conversion of all SQL, an in-house general-purpose SQL Parser, an in-house ORM, or an XA Transaction Manager implementation
- Unconditionally making the JPA/MyBatis/JDBC execution order identical
- Guaranteeing semantic equivalence of all concurrency/time/comparison and sorting behavior across DBMSs

## Architecture Decisions (ADR)

| ID | Decision | Rationale |
|---|---|---|
| ADR-001 | Prohibit Spring/Hibernate/MyBatis in Core | Isolate dependencies and compatibility |
| ADR-002 | Center the design on Compiler SPI | Allow switching external engines |
| ADR-003 | Default Observe + Rewrite Deny | Prevent legacy incidents |
| ADR-004 | Prioritize single-DataSource local transactions | Prevent misconceptions about distributed atomicity |
| ADR-005 | Do not mark support complete before passing actual integration tests for all four DBMSs | Prevent misrepresentation |
| ADR-006 | Separate Boot3/Boot4 Starters | Maintain major-version compatibility |
| ADR-007 | Prohibit distribution before SQL engine license approval | Legal/business risk |
| ADR-008 | Link SQL approval to SQL/schema/engine/test versions | Invalidate approval upon changes |

## Release Decision

Quantify the practical value of SQL analysis, the cost of integration into legacy systems, the benefits relative to the code volume of the new DSL, and actual transaction regression test results in the POC. If the benefits remain unclear, reduce the new API scope and focus on legacy analysis/verification.
