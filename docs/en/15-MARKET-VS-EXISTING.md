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

## Commercial viability experiments

- Introduce Observe mode into three different projects and measure changed business-code lines/regression results
- Classify an SQL inventory of 100 complex queries and compare the cost of testing against actual target databases
- Compare development time/code changes for the new DSL versus direct jOOQ use
- Evaluate licensing and operational burden

**Go/No-Go:** Productize only when UDAK's additional development/operating cost is lower than the benefit relative to what existing tools alone can achieve.

Official references: https://www.jooq.org/ ; https://mybatis.org/mybatis-dynamic-sql/docs/introduction.html ; https://docs.spring.io/spring-data/jpa/reference/
