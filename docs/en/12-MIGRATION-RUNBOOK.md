# Legacy Migration & Operations Runbook

English | [한국어](../ko/12-MIGRATION-RUNBOOK.md)

## Step 0 — Identify the target environment

- Collect application/Boot/JDK/Hibernate/MyBatis/Driver/DB versions
- Check the number of DataSources, TransactionManagers, and transaction propagation
- Inventory Mapper XML, JPQL, Native SQL, and JDBC SQL
- Check dependencies on DDL/procedures/hints/JSON/date/CLOB/sequences

## Step 1 — Baseline

- Preserve unit/integration/E2E/load test results from the existing project
- Collect SQL Query ID/Plan/average/p95 metrics
- Reproduce commit/rollback, flush/cache, and timeout behavior

## Step 2 — Observe only

- Install the UDAK Bridge: SQL modification features OFF
- Inspect SQL logging for sensitive information exposure
- Check for rollback/timeout/performance regressions
- If an anomaly occurs, immediately restore the previous behavior by removing the Bridge module or setting `enabled: false`

## Step 3 — Analyze

- Produce a Syntax/Capability/Type Compatibility Report for each DBMS
- Distinguish `SUPPORTED`, `UNSUPPORTED`, and `UNKNOWN`
- Prioritize SQL risks by usage frequency, business criticality, and complexity

## Step 4 — Selective Rewrite

- Select one low-risk SELECT query
- Approve the SQL hash/source/target/schema/provider version
- Test both the original and translated SQL against real databases and compare results
- Deploy selectively and record rollout/rollback
- Automatically disable rewriting when approval conditions change

## Step 5 — Gradually adopt the new API

- Consider the unified API for new business functionality
- Do not unconditionally rewrite existing Mappers/Entities
- Migrate only verified logic, in stages

## Failure/recovery

1. Detect a SQL error or result mismatch
2. Disable the approval rule for that query
3. Preserve incident logs/evidence
4. Roll back to the previous working build/configuration
5. If data correction is necessary, perform it separately according to a transaction/compensation plan
