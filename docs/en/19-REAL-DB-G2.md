# Dedicated real-database G2 — drivers, licenses and execution boundaries

English | [한국어](../ko/19-REAL-DB-G2.md)

## Decision

**Current minimal functional G2 PASS: 40 actual PostgreSQL/MySQL/SQL Server/Oracle checks and fixture cleanup completed.** Follow [managed results](20-MANAGED-G2-RESULTS.md) and [canonical G2 evidence](../../evidence/G2-REAL-VALIDATION.json) for the latest decision. This document defines driver/license and execution boundaries. Native SQL Server platform certification and product distribution approval remain separate and incomplete.

## Pinned validation versions

The SSOT is [g2-dependencies.json](../../tools/g2-dependencies.json). These are not added as Gradle product dependencies, and driver JARs are not committed.

| Profile | Validation JDBC artifact | Expected actual metadata version | License and scope |
|---|---|---|---|
| POSTGRESQL | org.postgresql:postgresql:42.7.14 | 42.7.14 | BSD-2-Clause; includes shaded-component notices |
| MYSQL | com.mysql:mysql-connector-j:26.10.0 | 26.10.0 | GPLv2 + Universal FOSS Exception 1.0; server 8.4+ candidate |
| SQLSERVER | com.microsoft.sqlserver:mssql-jdbc:13.6.2.jre11 | 13.6.2.0 | MIT; server-use rights are separate |
| ORACLE | com.oracle.database.jdbc:ojdbc17:23.26.4.0.0 | 23.26.4.0.0 | Actual JAR uses FDHUT; server 19c+ candidate |

The required graph includes `checker-qual:3.55.1` (MIT) and `protobuf-java:4.36.1` (BSD-3-Clause). Optional cloud/native/Kerberos/XA/OSGi features are outside scope. PostgreSQL shaded SCRAM/stringprep notices are checked. Protobuf inherits its license from a pinned parent POM, so that POM and upstream LICENSE are checked together. SQL Server's JAR has no license file, so the MIT text from its pinned source tag is checked separately.

- [PostgreSQL downloads](https://jdbc.postgresql.org/download/) and [versioned BSD text](https://raw.githubusercontent.com/pgjdbc/pgjdbc/REL42.7.14/LICENSE).
- [MySQL compatibility](https://dev.mysql.com/doc/connector-j/en/connector-j-versions.html) and [GPL/FOSS text](https://raw.githubusercontent.com/mysql/mysql-connector-j/26.10.0/LICENSE). The FOSS exception is not arbitrary permission for proprietary UDAK distribution. If server 8.0 is required, review and verify a separate pin such as 9.7.0.
- [Microsoft JDBC versions](https://learn.microsoft.com/en-us/sql/connect/jdbc/download-microsoft-jdbc-driver-for-sql-server?view=sql-server-ver17) and [MIT text](https://raw.githubusercontent.com/microsoft/mssql-jdbc/v13.6.2/LICENSE).
- [Oracle downloads and JDK/DB scope](https://www.oracle.com/database/technologies/appdev/jdbc-downloads.html) and [FDHUT text](https://download.oracle.com/otn-pub/otn_software/jdbc/FDHUT_LICENSE.txt). The POM says FUTC while the actual JAR's `META-INF/license.txt` contains FDHUT. Recheck binary terms, bundled text, rights notices and separate contracts for product distribution.

This review covers original texts and integrity of unmodified validation artifacts. Product redistribution approval, including MySQL GPL/FOSS applicability and Oracle organizational contracts, is `NOT_GRANTED`. JDBC driver licensing does not approve server licensing. No comprehensive vulnerability scan is claimed.

## Dedicated connection contract

The default path is the directly implemented `DedicatedRuntimeProvider` and managed runner. As an alternative for external environments, an owner-reviewed external JAR must provide four `RealDatabaseProvider` implementations and `META-INF/services/dev.udak.testkit.RealDatabaseProvider` registration. Each implementation must return its exact profile, a programmatic `DataSource`, and `dedicatedSchemaApproved() == true`. Only owned fixtures in dedicated test schemas may be created/dropped; existing business tables must not be used.

The operator prepares DataSources without asking the agent to open secret files or transmitting passwords or connection URLs. Providers must enforce connection/read timeouts and must not emit raw information through pools, file loggers, DriverManager logWriter or independent JUL handlers. Share only provider JAR paths and approved test scope. Local providers and configuration may be kept in `.g2-local/`, excluded by both Git and Docker. The harness does not read secret configuration or copy/print provider JARs.

Product platform certification for SQL Server follows the [official Intel/AMD x86-64 Linux scope](https://learn.microsoft.com/en-us/sql/linux/containers/deploy?view=sql-server-ver17). ARM64 Rosetta/QEMU execution is not officially tested or supported. For this minimal functional G2, after the user authorized directly preparing dedicated environments on 2026-11-18, query and transaction tests against **actual SQL Server** under emulation are permitted. All four DBMSs must pass the same 10 checks, fixture cleanup and server stop; native SQL Server execution and vendor platform certification remain separately NOT RUN. No checks are omitted and no product support is declared. Confirm dedicated ownership, health, resources and use rights while preserving existing VMs and databases.

## Bounded execution

```bash
# Verify pinned dependencies/licenses and driver loading only; no connections.
# Intentionally exits 2 (INCOMPLETE) while four real databases remain unexecuted.
python3 tools/run-g2.py

# Run all four only with owner-prepared and reviewed dedicated providers.
python3 tools/run-g2.py --run --provider-jar .g2-local/approved-providers.jar
```

Execution is sequential: 360 seconds total, 45 seconds per profile, 30 child CPU seconds, JVM heap 256MiB/metaspace 128MiB/active CPUs 2. Workspaces are limited to 2,000 entries/128MiB. Driver JAR/POM SHA512, published checksums, required graphs, license entries and upstream text hashes are rechecked. The live classpath uses main sources only, excluding the H2 JAR and test provider registration.

Each profile checks product name, driver name and pinned metadata version before running 10 CRUD/NULL/page/bind/commit/rollback/delete checks. This is the minimal API capability scope. JOIN/batch/upsert, timezone/collation equivalence, broad server-version support, Oracle 11g, legacy ORMs and performance need separate validation. Public metadata contains numeric major/minor versions only; URL/user/catalog/schema, raw server strings and original exceptions are not printed. Oracle metadata formatting on a real server is still NOT RUN.

The parent creates `udak_p2_<12hex>` fixture names and durably records them **before** execution in `.git/udak-g2/live-intents/`. Execution start, fixture identity and unconfirmed cleanup survive forced termination. Only owned tables with confirmed CREATE success are dropped. Uncertain CREATE/DROP/interruption stops subsequent profiles and preserves fixture evidence and database state. There are no arbitrary retries or automatic leftover-table deletions.

stdout/stderr and existing JUL loggers are blocked before provider loading and throughout process termination; only approved result protocol is printed. Independent provider file loggers/handlers remain an operator-review boundary. Success, failure and normal interruption use the existing common guard's single cleanup path, reclaiming only owned regenerable workspaces. Databases, providers, secret configuration, intent/failure evidence and pre-existing uncertain artifacts are preserved. Cleanup of arbitrary external commands is not guaranteed.

## Evidence from the 2026-11-17 preparation run

- Core smoke, basic SPI 74, external SPI 83, CRUD API 313, Spring JDBC/H2 and DB foundation/failure-path 69 checks PASS. H2/proxy contracts are not real-database results.
- Six pinned artifacts, 12 JAR/POM checksums, upstream licenses/parent POM, loading all four actual drivers and five evidence-protocol tests PASS. `run-g2.py` returned exit 2 / INCOMPLETE because all four real profiles are NOT RUN.
- Initial driver verification mistook License/Notice class names for license texts. The filename filter was corrected, direct/inherited Protobuf licensing was separated, and validation reran. Failed reports are preserved under `.git/udak-g2/previous-reports/`.
- Final regression workspace: 62 files/8,493,628 bytes; final G2 workspace: 11 files/16,293,792 bytes automatically removed with no remainder. Two driver inspection workspaces also removed 28 files/16,345,451 bytes. Pre-existing uncertain diagnostic evidence was preserved.
- Actual execution used javac/java and Python harnesses. No new DB, Docker container, Gradle, Boot/ORM app or performance test was started. Auxiliary worktrees created/removed/remaining: 0.

## Next work

Minimal functional G2 passed; proceed to Phase 3 FR-005~007 / T-011~013 JPA/MyBatis/JdbcTemplate Observe and legacy-access compatibility. Preserve default Rewrite denial and Core dependency boundaries. Broad server certification, graceful shutdown/recovery, timezone/collation equivalence and performance are outside this completion scope.
