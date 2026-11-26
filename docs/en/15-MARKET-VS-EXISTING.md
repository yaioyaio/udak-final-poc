# Market fit / Existing Libraries / Buy vs Build

English | [한국어](../ko/15-MARKET-VS-EXISTING.md)

## Validate product differentiation

| Existing library | Capabilities already provided | Capabilities not to reimplement | Potential UDAK-specific value |
|---|---|---|---|
| Spring Data JPA/Hibernate | JPA Repository/ORM/Dialect | JPA EntityManager/dirty checking | Diagnostics for mixed technology/DB configurations |
| MyBatis/MyBatis-Spring | XML Mapper/transaction integration | SQL executor/Mapper capabilities | Query inventory/compatibility approval |
| Spring JdbcTemplate | Connection/PreparedStatement management | The entire JDBC utility set | Central SQL policy/legacy diagnostics |
| jOOQ | Fluent SQL DSL/Dialect/parsing | A complete new SQL DSL | Control plane/legacy evidence |
| MyBatis Dynamic SQL | SQL builder, MyBatis/Spring JDBC rendering | Basic query builder | Diagnostics including JPA/gradual adoption |
| Flyway/Liquibase | Schema migrations | Schema migration engine | Linking schema versions to SQL approval |

## Who benefits / who may not

**Core audience:** SI/SM, commercial solutions supporting multiple DBMSs, existing services mixing MyBatis/JPA, and backend teams responsible for DB migration.

**Optional audience:** Single PostgreSQL+JPA services, small CRUD applications, and systems with DBMS-specific high-performance queries. Existing technologies may already be sufficient.

## T-001 customer workflows

These five customer demand hypotheses draw on public project cases and existing technical validation. Target customer interviews, production adoption, and confirmation of purchase intent are **NOT RUN**. [Roadmap](09-WBS-ROADMAP.md) · [Traceability](16-TRACEABILITY.md)

| ID | Stakeholder and trigger | Workflow and control | Measurable success criteria | Technical evidence and limits |
|---|---|---|---|---|
| T-001-S1 | A legacy maintainer introduces SQL observation while managing the risk of a device registration regression. | Run the same original ThingsBoard registration and lookup test and failure rollback test with Observe OFF and ON. With Observe ON, attach the Hibernate inspector at one test configuration point. | Both business tests pass with Observe OFF and ON. OFF captures zero events. ON captures 17 registration and lookup events and seven rollback events, with zero dropped or unobservable events in both tests. | The published tests covered synchronous calls on isolated PostgreSQL 18. Customer production environments and other workflows remain unverified. [External pilot](34-LEGACY-ADOPTION-PILOT.md#thingsboard-ce-external-pilot) · [OFF/ON execution evidence](../../evidence/THINGSBOARD-OBSERVE-AND-SQL-CHANGE-VALIDATION.json) |
| T-001-S2 | A PR reviewer needs to distinguish a change in device count SQL from variation in request values. | Run the ThingsBoard PR's before and after COUNT SQL against the same PostgreSQL fixture and compare fingerprints for the same logical query. Use a run with only the bound UUID changed as the control. | The report shows one removed fingerprint, one added fingerprint, and one affected replay test. The value-only control reports zero changes. | The replay covered fixed SQL from a public PR and isolated data. Full application execution at the historical revisions and customer PR review outcomes remain unverified. [ThingsBoard PR #14858](https://github.com/thingsboard/thingsboard/pull/14858) · [SQL replay evidence](../../evidence/THINGSBOARD-OBSERVE-AND-SQL-CHANGE-VALIDATION.json) |
| T-001-S3 | A DBA and QA reviewer check whether observed schema drift affects device lookup before a deployment. | Compare baseline and changed JDBC schema metadata and link the observed fingerprint to reviewed dependencies. When `device.customer_id` is removed, match the schema hash before replaying the selected registered test. Use an unused column length change as the control. | Both reports are `COMPLETE`. Removing the column selects one test and reproduces SQLSTATE `42703`. The unused column change selects zero tests and retains the baseline query result and fingerprint. | The public Flyway issue reports that `validate` omitted a checksum mismatch for an applied baseline migration. UDAK evidence covers a separate lookup on isolated PostgreSQL 18. Reproduction of the Flyway issue and application to customer schemas remain unverified. [Flyway #4106](https://github.com/flyway/flyway/issues/4106) · [Device schema impact evidence](../../evidence/THINGSBOARD-DEVICE-SCHEMA-IMPACT-VALIDATION.json) |
| T-001-S4 | A Spring maintainer reviews the local transaction boundary while changing order, stock, and audit writes together. | Save and explicitly flush the JPA order, reserve stock through MyBatis, and write the audit entry with JdbcTemplate on a shared DataSource. Compare success with a failure after all three writes. Use a separate trace test to check participation and visibility before and after flush. | The successful path commits all three effects and the failure rolls back all three. The trace test confirms that all three access paths participate in the same local boundary and checks the change in MyBatis visibility across flush. | A public report about flush before a stored procedure call motivates reviewing the boundary. UDAK validated separate Spring/H2 order and trace fixtures. Reproduction of the public issue, customer databases, general cache and flush behavior, and distributed transactions remain unverified. [Spring Data JPA #3434](https://github.com/spring-projects/spring-data-jpa/issues/3434) · [Order pilot](../../evidence/ORDER-ADOPTION-PILOT-VALIDATION.json) · [Boundary trace evidence](../../evidence/TX-TRACE-VALIDATION.json) |
| T-001-S5 | An operations engineer needs to prevent duplicate processing after a critical write loses its JDBC commit response. | Validate commit response loss on isolated PostgreSQL and MySQL. When the client cannot determine the outcome, check the `TransactionGuard` denial and reconcile the actual commit on a separate connection. | The JDBC commit call fails and automatic retry is blocked on both databases. An independent query confirms that the write was committed exactly once. | The public pgjdbc issue separately reports handling of an XA outcome after backend termination. Local evidence covers a single JDBC transaction on the specified PostgreSQL and MySQL profiles. XA, customer incident response, and other database and driver combinations remain unverified. [pgjdbc #4438](https://github.com/pgjdbc/pgjdbc/issues/4438) · [Commit response loss evidence](../../evidence/PRODUCT-G5-FAILURE.json) |

## Follow-up customer validation protocol

With the target team's approval, agree on the workflow, change and control cases, expected results, and review scope in an isolated environment. Run the current process and the process with UDAK against the same changes and criteria. For each, record setup and review time, review coverage and the total number of eligible cases, true findings, false positives, missed findings, and unverified coverage. Retain only participant roles, synthetic case IDs, elapsed times, and aggregate counts. Exclude raw SQL, inputs and results, original identifiers, account details and credentials, and raw logs from collection.

The experiment to introduce Observe into three different projects and measure changed business-code lines and regression outcomes remains incomplete. Base the productization decision on benefits and costs measured against each customer's current process.

## Commercial viability experiments

- Introduce Observe mode into three different projects and measure changed business-code lines/regression results
- Classify an SQL inventory of 100 complex queries and compare the cost of testing against actual target databases
- Compare development time/code changes for the new DSL versus direct jOOQ use
- Evaluate licensing and operational burden

**Go/No-Go:** Productize only when UDAK's additional development/operating cost is lower than the benefit relative to what existing tools alone can achieve.

Official references: https://www.jooq.org/ ; https://mybatis.org/mybatis-dynamic-sql/docs/introduction.html ; https://docs.spring.io/spring-data/jpa/reference/
