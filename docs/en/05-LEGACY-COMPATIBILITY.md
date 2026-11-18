# Legacy Compatibility — JPA / MyBatis / JdbcTemplate

English | [한국어](../ko/05-LEGACY-COMPATIBILITY.md)

## 1. Policy

The default is **OBSERVE**, which does not change the behavior of existing business source code. `ANALYZE` reports SQL compatibility. `REWRITE` applies only to specific Queries backed by approval and actual regression tests.

## 2. Boundaries by Integration Adapter

### JPA/Hibernate
- `StatementInspector` is a point for inspecting SQL strings, not a general-purpose solution for complex binding/result structure conversion.
- Observing actual SQL at the JDBC/DataSource boundary can reduce interference.
- JPA remains responsible for flush, first-level cache, lazy loading, dirty checking, and related behavior.
- Do not rewrite existing JpaRepository and Entity code.

### MyBatis
- Keep Mapper XML and `@Mapper` intact.
- Identify the MappedStatement ID, BoundSql, and SQL information at execution time.
- Interceptors can break cache keys/ParameterMapping/ResultMap, so the MVP focuses on observation.
- Dynamic SQL requires Fingerprint and contract verification **for each final bound structure**.

### JdbcTemplate
- Observe at the DataSource/Connection boundary of the Spring JDBC execution path.
- SQL substitution must be verified for effects on ? parameter count/order/column label/RowMapper as well.
- Preserve existing JdbcTemplate.query/update usage.

## 3. Approval-based Conversion Steps

1. Identify existing SQL: framework + query id + source SQL / fingerprint
2. Assess SQL parser/provider: whether parsing is supported
3. Check Capability + bind/result contracts
4. Execute the original and converted queries separately for testing
5. Obtain input/output/time/concurrency regression evidence
6. Record provider/dialect/schema/SQL versions in the approval Registry
7. Activate in production: allow only specific Queries; fail closed on mismatch
8. rollback: disable only the relevant Query rule and restore the previous approved rule

## 4. Approval Example (design proposal; runtime file handling not implemented)

```yaml
legacy:
  default-mode: observe
  rewrite:
    enabled: false
    approvals:
      - query-id: UserMapper.selectUsers
        framework: mybatis
        sql-sha256: '...'
        source-dialect: mysql-8
        target-dialect: oracle-19
        schema-revision: v3
        sql-provider-version: validated-version
        evidence-id: COMPAT-USER-001
        review-revision: r1
```

## 5. Default Scope That Must Not Be Converted

DDL, stored procedure, dynamic DDL, SQL hint, lock hint, vendor-specific types, uncontrolled native SQL, write statement with side effects, JPA association fetching rewrites.

## 6. Rollback

It must be possible to turn the Bridge OFF. In addition to configuration toggles, SQL rewrite requires version control of the approval Registry and rollback evidence per deployment unit. Arbitrary fallback to source SQL on transient errors is prohibited by default.

## Phase 3 implementation and validation

Implemented explicit registration of HibernateObserveInspector, MyBatisObserveInterceptor and ObserveDataSource. Four existing Entity/Repository/Mapper/service sources remain unchanged. Observe OFF/ON flush/cache/commit/rollback and mapping comparisons passed on actual H2, PostgreSQL, MySQL, SQL Server and Oracle. There is no SQL translation or automatic flush/cache correction. Events represent their call/prepare/execute-attempt boundaries rather than all successful database executions. See [Phase 3 results](21-LEGACY-OBSERVE-RESULTS.md) and [G3 evidence](../../evidence/PHASE3-GATE.json).
