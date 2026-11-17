# Phase 1 SQL engine and license evaluation

English | [한국어](../ko/17-SQL-ENGINE-EVALUATION.md)

Review date: 2026-11-17. Requirement IDs: **P1-ENGINE / T-002, P1-SPI / FR-001, P1-PROVIDER / FR-003·004**.

This PoC selects **upstream `com.github.jsqlparser:jsqlparser:5.4`, using the Apache-2.0 option, in a parser-validation adapter outside Core**. An actual external parser checks SQL emitted by the existing limited renderer to verify SPI replaceability. This does not complete a dialect translator or a legacy SQL Rewrite runtime. Final execution status comes from evidence in [traceability](16-TRACEABILITY.md) and [PoC results](14-POC-RESULTS.md).

## Comparison criteria

Parsing reads SQL into an AST; rendering emits SQL from a model; translation carries source-dialect semantics into a target dialect. Successful parsing or matching output strings does not establish database execution or result equivalence. Schema, functions, types, NULL behavior, ordering, and pagination across four DBMSs require separate real-database tests.

| Candidate and reference | Capabilities and UDAK fit | JDK and dependencies | License and edition assessment |
|---|---|---|---|
| jOOQ 3.21 line; source POM 3.21.9 | DSL, parser, dialect renderer, and parser-to-target-dialect rendering; future translation candidate | OSS 3.21 requires Java 21. For Java 17, consider OSS 3.19 or the appropriate commercial Java 17 distribution. The 3.21.9 POM includes R2DBC SPI, SLF4J, and optional JAXB; resolve the selected artifact's dependencies | OSS Apache-2.0. Evaluate Professional/Enterprise for general commercial Oracle/SQL Server editions; distinguish Express database coverage |
| Apache Calcite 1.42.0 | Parser, validator, relational algebra, optimizer, and dialect unparsers; future schema/type-aware analysis candidate | Official HOWTO includes JDK 17 among build prerequisites. UDAK Java 17 execution is NOT RUN. Broader dependencies include linq4j, Avatica, Guava, and Jackson | Apache-2.0; inspect the actual distribution's complete dependencies and notices |
| JSqlParser upstream 5.4 | SQL↔AST, visitors, and deparsing; used here only to syntax-check limited generated SQL | Pinned POM targets Java release 11 with build toolchain `[17,24)`. Declared dependencies are test-scoped, without direct compile/runtime dependencies; artifact/JDK checks require execution evidence | Choice of LGPL-2.1 or Apache-2.0; this PoC selects Apache-2.0 |

jOOQ references: [parser translation](https://www.jooq.org/doc/latest/manual/sql-building/sql-parser/sql-parser-translator/), [JDK matrix](https://www.jooq.org/download/support-matrix-jdk), [3.21.9 POM](https://raw.githubusercontent.com/jOOQ/jOOQ/version-3.21.9/jOOQ/pom.xml), and [edition comparison](https://www.jooq.org/download/). Calcite references: [capabilities](https://calcite.apache.org/docs/), [1.42.0 download](https://calcite.apache.org/downloads/), [build prerequisites](https://calcite.apache.org/docs/howto.html), and [pinned dependencies](https://raw.githubusercontent.com/apache/calcite/calcite-1.42.0/core/build.gradle.kts). JSqlParser references: [pinned README](https://raw.githubusercontent.com/JSQLParser/JSqlParser/jsqlparser-5.4/README.md) and [pinned POM](https://raw.githubusercontent.com/JSQLParser/JSqlParser/jsqlparser-5.4/pom.xml).

## Four-DBMS scope

| Candidate | PostgreSQL | MySQL | SQL Server | Oracle |
|---|---|---|---|---|
| jOOQ | OSS dialect scope; check versions | OSS dialect scope; check versions | Outside OSS; distinguish Express DBs from general editions | Outside OSS; distinguish Express DBs from general editions |
| Calcite | `PostgresqlSqlDialect` | `MysqlSqlDialect` | `MssqlSqlDialect` | `OracleSqlDialect` |
| JSqlParser | Combined grammar target | Combined grammar target | Combined grammar target; quoted-identifier configuration matters | Combined grammar target |

Apply jOOQ's [edition database list](https://www.jooq.org/download/) together with its [RDBMS version matrix](https://www.jooq.org/download/support-matrix). Calcite exposes these classes in its [JDBC dialect unparser API](https://calcite.apache.org/javadocAggregate/org/apache/calcite/sql/dialect/package-summary.html). JSqlParser's scope follows the [upstream grammar targets](https://raw.githubusercontent.com/JSQLParser/JSqlParser/jsqlparser-5.4/README.md). This table classifies provider capabilities; it is not UDAK's completed support matrix. All real-database checks here are **NOT RUN**. Multiple rendering profiles, such as Oracle 11g/12c, do not count as additional DBMSs or real-database evidence.

## Selection rationale and artifact identity

JSqlParser supplies AST parsing for a limited SPI experiment within a small dependency boundary. It avoids implementing a general parser and preserves dependency-free Core. jOOQ remains a translation candidate after JDK, edition, and contract selection. Deferring Calcite is a design judgment: planner/metadata integration exceeds this compiler-contract experiment. No speed or memory advantage is claimed; performance testing is not executed.

- Pinned coordinate: `com.github.jsqlparser:jsqlparser:5.4`; source tag: `jsqlparser-5.4`.
- Distribution checks target the [Maven Central POM](https://repo.maven.apache.org/maven2/com/github/jsqlparser/jsqlparser/5.4/jsqlparser-5.4.pom), [JAR](https://repo.maven.apache.org/maven2/com/github/jsqlparser/jsqlparser/5.4/jsqlparser-5.4.jar), and [published SHA-512](https://repo.maven.apache.org/maven2/com/github/jsqlparser/jsqlparser/5.4/jsqlparser-5.4.jar.sha512). Execution evidence records actual hashes, size, and class versions.
- Do not mix upstream with the README/current website's recommended Manticore coordinate, `com.manticore-projects.jsqlformatter:jsqlparser`. Do not adopt floating versions or documentation example versions. Even the tagged README's installation guidance cannot replace artifact/POM identity checks.
- The orchestrator's preliminary artifact inspection found no LICENSE/NOTICE entries inside the JAR. Copying the JAR alone cannot establish license-notice compliance. Bundle the pinned tag's license separately and verify that bundle.

## License application and distribution conditions

JSqlParser's choice is supported by its dual-license README/POM and [pinned LICENSE_APACHEV2](https://raw.githubusercontent.com/JSQLParser/JSqlParser/jsqlparser-5.4/LICENSE_APACHEV2). Apache-2.0 requires a license copy, modification notices, retention of applicable original notices, and relevant NOTICE attribution when supplied upstream. It grants no general trademark rights or unconditional warranty. Selecting this option does not mean simultaneously applying the LGPL option or omitting notices.

Calcite requires review of its [1.42.0 Apache-2.0 license](https://raw.githubusercontent.com/apache/calcite/calcite-1.42.0/LICENSE) and included-component notices. For jOOQ, separate OSS and commercial paths using its [license overview](https://www.jooq.org/legal/licensing); confirm developer and redistribution scope against the [official commercial agreement](https://www.jooq.org/legal/250331_jOOQ_License_and_Maintenance_Agreement.pdf) and the actual contracting entity. Engine licensing does not eliminate third-party obligations.

This assessment establishes **the basis for a license option used in technical PoC validation**. It does not replace ADR-007 product-distribution approval, legal review, commercial contracting, or purchasing approval. A POM without runtime dependencies does not establish a completed provenance audit or vulnerability scan of included code. Recheck the actual package's notices and selected coordinates before external distribution.

## Verification gates

| Gate | Required evidence | Status in this document |
|---|---|---|
| P1-ENGINE / T-002 official comparison | Official sources above, pinned identity, license choice, and limits | Documentation research complete |
| Pinned artifact integrity and license bundle | POM/JAR/license hashes, dependency scopes, missing JAR notices, and separate bundle checks | Final status references separate execution evidence in traceability/PoC results |
| P1-SPI / FR-001 | Same contract for basic/external providers: binding order, no value inlining, immutability, invalid-input rejection | Execution owner's verification; this document alone is not PASS |
| P1-PROVIDER / FR-003·004 | Java 17 target compilation, actual parser invocation, limited profiles, and failure paths | Execution owner's verification; this document alone is not PASS |
| Real DBs, legacy translation, product distribution | Separate follow-up verification and approval | NOT RUN |

Documentation comparison alone cannot complete Phase 1. Artifact and contract tests linked from the [traceability plan](16-TRACEABILITY.md) must actually PASS. This document-writing task itself ran no builds, tests, applications, databases, or Docker workloads.
