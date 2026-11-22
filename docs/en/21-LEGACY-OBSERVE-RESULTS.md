# Phase 3 Legacy Observe Results (2026-11-18)

English | [한국어](../ko/21-LEGACY-OBSERVE-RESULTS.md)

## Validation results

| Requirement ID | Scope | Result |
|---|---|---|
| P3-OBS / FR-005~008 / T-011~013 | JDK-only compilation and execution of `observe-core` without an external classpath, plus `legacy-observe` adapter contracts | PASS (202 + 188 assertions) |
| P3-COMPAT / FR-005~007·010 | Mixed access through a shared DataSource in `legacy-compat-testkit` | H2 10 checks PASS, G3 40 checks across 4 managed real DBMSs PASS |
| P3-HARNESS | Java 17 target compilation, existing Core contracts and smoke, pinned dependencies and automatic cleanup | PASS (Core 74 checks + smoke) |

The runs used Hibernate 6.6.53.Final, Spring Framework 6.2.19, Spring Data JPA 3.5.13, MyBatis 3.5.19, and MyBatis-Spring 3.0.5. Evidence records the real DB image pins and detailed execution results. [Final G3 gate](../../evidence/PHASE3-GATE.json) · [Local validation](../../evidence/PHASE3-VALIDATION.json) · [Real DB validation](../../evidence/PHASE3-REAL-VALIDATION.json) · [Traceability](16-TRACEABILITY.md)

| DBMS | Server version | Pinned driver version | Result |
|---|---|---|---|
| H2 | 2.3.232 | 2.3.232 | 10/10 PASS |
| PostgreSQL | 17.12 | 42.7.14 (`checker-qual` 3.55.1) | 10/10 PASS |
| MySQL | 8.4 | 26.10.0 (`protobuf-java` 4.36.1) | 10/10 PASS |
| SQL Server | 16.0 | 13.6.2.jre11 | 10/10 PASS (linux/amd64 emulation) |
| Oracle | 23.26 | 23.26.4.0.0 | 10/10 PASS |

The real DB runs reused the 6 existing G2 driver and transitive dependency pins. [G2 driver manifest](../../tools/g2-dependencies.json) · [Real DB image manifest](../../tools/g2-server-images.json)

All 8 behavior checks passed with Observe OFF as the baseline and again with Observe ON. The tests reused the existing Entity, Repository, Mapper, and `MixedUserService` unchanged. They checked a shared physical connection, visibility of dirty UPDATEs before and after explicit flush, stale JPA/MyBatis cache entries and explicit refresh/clear, commit/rollback across all 3 access paths, JDBC RowMapper, and MyBatis ResultMap. The 2 event metadata and listener failure checks ran with Observe ON.

## Observe contract and limits

- Events are emitted at Hibernate `StatementInspector`, MyBatis `StatementHandler.prepare`, and JDBC `execute*` attempts. These points cannot establish the number of successful DB executions. MyBatis cache hits that skip prepare emit no prepare event.
- Events contain enums and 2 SHA-256 hashes. They omit raw SQL, bindings, literals, raw IDs, connection or account details, and original exceptions. SQL shape input is bounded to 16,384 characters and raw query ID input to 256 characters. Unsupported `EXEC`, ambiguous strings, and multiple statements collapse to `UNAVAILABLE`. Quoted identifiers normalize to a common token, so distinct SQL can share a shape hash.
- The shape fingerprint groups inventory entries. Approval still uses the exact-SQL hash contract of Core `SqlFingerprint`. Observe emits events, while the application and frameworks own flush and caches. SQL rewrite is outside Phase 3 scope.
- The sink runs synchronously. Its owner is responsible for thread safety and prompt, nonblocking return. Nonfatal observation failures are isolated, while `VirtualMachineError` and `ThreadDeath` propagate.
- When MyBatis cursor or nested internal calls bypass the Executor proxy, they use the nearest intercepted parent ID or a shape-based fallback. JPA/JDBC also use a shape-based fallback and have no automatic call-site ID.
- Raw objects from vendor `unwrap`, JDBC connection builders, `ResultSet.getStatement`, and `DatabaseMetaData.getConnection` bypass observation. Plain `Statement` batch SQL is outside coverage. Wire the shared wrapper explicitly. The owner manages the raw DataSource and pool lifecycle.

## Dependencies and execution bounds

Public Maven dependency resolution ran with the Spring Boot 3.5.16 BOM. POM licenses, checksums, and applicable notices were checked for 36 JARs (37,749,029 B). The adapters use LGPL Hibernate as a `compileOnly` dependency. No Phase 3 library binaries are bundled in the repository. Product redistribution approval is **NOT GRANTED**. [Phase 3 dependency manifest](../../tools/phase3-dependencies.json)

| Item | Bounds and cleanup results |
|---|---|
| Child processes and JVMs | CPU time 30 s, heap 256 MiB, metaspace 128 MiB, 2 active CPUs |
| Dedicated real DBs | 1 active DB, up to 4 GiB, 2 CPUs, and 512 PIDs each, restart policy `no`, log driver `none`, loopback binding |
| Final H2 and real DB workspaces | Automatically removed 105 entries and 37,951,356 B for H2 and 143 entries and 54,312,032 B for real DBs, with 0 workspaces remaining |
| Containers and data | Atomic journal before creation. Finalization stopped containers and preserved data. All 4 new Phase 3 DBs and 4 prior G2 DBs are stopped (8/8), with 0 existing resource modifications and 0 DB containers or volumes deleted. Data size was unmeasured. |

SQL Server stopped with exit 137 and OOM flag false, Oracle with 143, and PostgreSQL and MySQL with 0. G3 covers functionality on the pinned environments. Graceful shutdown and restart recovery, native SQL Server platform certification, performance and load, Gradle tasks, Spring Boot autoconfiguration, and Boot 3/4 certification are **NOT RUN**. [Container retention summary](../../evidence/PHASE3-CONTAINER-RETENTION.json)

## Compose an existing Hibernate inspector (NEXT-003)

Set the application’s Hibernate inspector explicitly. When Observe is enabled, compose its existing inspector with the observer.

```java
StatementInspector inspector = observeEnabled
        ? HibernateObserveInspector.compose(existingInspector, observer)
        : existingInspector;
factory.getJpaPropertyMap().put("hibernate.session_factory.statement_inspector", inspector);
```

The composition calls the existing inspector once with the original SQL and returns its result to Hibernate verbatim. When the result is `null`, Hibernate uses the original SQL, so Observe records that SQL's metadata. An exception from the existing inspector propagates before an observation is emitted. [Hibernate 6 inspector contract](https://raw.githubusercontent.com/hibernate/hibernate-orm/6.6/hibernate-core/src/main/java/org/hibernate/resource/jdbc/spi/StatementInspector.java)

Run `python3 -B tools/run-hibernate-observe.py` for the bounded checks. Hibernate 6.6.53.Final with H2 2.3.232 passed four composition scenarios covering the existing inspector, business results, mixed rollback and effective-SQL events with Observe OFF and ON. Adapter contracts (213 checks), the ten original H2 scenarios and Core smoke also passed. The run used in-memory H2 and reclaimed its temporary workspace. The four external DB profiles for this composition are NOT RUN. [Execution evidence](../../evidence/HIBERNATE-INSPECTOR-VALIDATION.json)

## Reproduction and next phase

```bash
python3 tools/run-phase3.py
python3 tools/run-phase3-real.py
python3 tools/verify-phase3.py
```

The first command runs H2 validation, the second runs the dedicated real DBs, and the third checks preserved evidence statically. The retention cap of 8 has been reached. A rerun that creates new dedicated DBs requires capacity through authorized reuse or reclamation. The runner does not automatically delete databases.

Phase 4 Transaction Consistency Guard covers DataSource and transaction manager misconfiguration plus propagation, readOnly, timeout, and isolation diagnostics. Its scope is local transaction diagnostics, without an XA atomicity guarantee. [Transaction consistency design](06-TRANSACTION-CONSISTENCY.md)
