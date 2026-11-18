# Managed real-database G2 results

English | [한국어](../ko/20-MANAGED-G2-RESULTS.md)

## Minimal functional verdict

**G2 PASS.** All 40 minimal CRUD/Query and Spring JDBC local transaction checks passed across 4 dedicated real databases. Each profile ran INSERT_NULL, READ_NULL, UPDATE, INSERT_SECOND, INSERT_THIRD, PAGE, BIND, COMMIT, ROLLBACK, and DELETE, with fixture cleanup and server shutdown confirmed. [G2-REAL-VALIDATION.json](../../evidence/G2-REAL-VALIDATION.json)

| Profile | Real server version | Pinned JDBC driver | Platform | Result |
|---|---|---|---|---|
| POSTGRESQL | 17.12 | postgresql 42.7.14 | linux/arm64 | 10 PASS |
| MYSQL | 8.4 | mysql-connector-j 26.10.0 | linux/arm64 | 10 PASS |
| SQLSERVER | 16.0 (2022) | mssql-jdbc 13.6.2.jre11 (metadata 13.6.2.0) | linux/amd64 | 10 PASS |
| ORACLE | 23.26 Free | ojdbc17 23.26.4.0.0 | linux/arm64 | 10 PASS |

The adjacent regression report on the same host recorded JDK 21.0.13; the G2 JVM version was not separately probed. Compilation targeted `--release 17`, with Spring JDBC/Tx 6.2.19. Server images were pinned by platform-specific digest. One batch ran SQL Server alone and the other ran the remaining 3 profiles using identical source. Each batch reports INCOMPLETE for the full gate because it ran a subset. The consolidated evidence records PASS for all 4 profiles. [Server image manifest](../../tools/g2-server-images.json) · [SQL Server batch](../../evidence/G2-RUN-SQLSERVER.json) · [Other database batch](../../evidence/G2-RUN-OTHER-DATABASES.json)

## Execution and retention

- The Python harness and Java JDBC runner started 4 new databases sequentially. At most 1 instance was active, with per-container limits of 2 CPUs, 4 GiB of memory, and 512 PIDs. Ports were published on loopback only and automatic restarts were disabled. The 64 existing Docker containers and Parallels VM were untouched, and the VM was not resumed.
- Preflight requires at least 40 GiB of free disk and 1 GiB of memory headroom. The 2 GiB image pull limit applies to progress reported by Docker Engine. Total disk use is outside that limit. A `compressed_layer_bytes` entry of 0 means compressed layer sizes were unavailable in the OCI verbose metadata.
- The harness generated fresh credentials in memory and passed them through an HTTP request over the Docker Engine Unix socket and through private Java stdin. `DedicatedRuntimeProvider` uses this input to construct a dedicated `DataSource`. Values were kept out of dotenv files, command arguments, logs, evidence, and model input. The Docker daemon can retain values in stopped container environment settings. `Config.Env` and raw application logs were left unread.
- The run confirmed DROP for all 4 fixtures and exit for all 4 containers. It retained dedicated DB data, writable container layers, and 2 anonymous volumes (PostgreSQL and MySQL). Total data size was unmeasured and the managed container retention limit is 8. PostgreSQL and MySQL recorded exit 0, SQL Server recorded exit 137 after a Docker stop request with a 30-second timeout, and Oracle recorded exit 143. All 4 reported OOMKilled=false, and the 64 existing containers continued running. [Container retention evidence](../../evidence/G2-CONTAINER-RETENTION.json)
- The common runner automatically removed 107 regenerable workspace files (45,380,214 bytes). The run intent and audit journal were preserved under `.git/`. Pre-existing audit material of unknown purpose was excluded from cleanup. Automatic cleanup was verified on the paths wired to the common runner.

## Regression and unverified scope

| Verification | Result |
|---|---|
| Phase 2 regression | PASS · Core smoke, 74 basic SPI checks, 83 external SPI checks, 313 CRUD API checks, Spring JDBC/H2, 71 DB foundation checks, 128 dedicated provider contract checks |
| Managed safety controls | 7 PASS · creation bounds and public result redaction, ownership, DB container deletion prevention, volume retention for exited probes, loopback, preservation on failed atomic replacement, private pipe |
| Real DB evidence verifier | 6 PASS · accepts complete evidence and rejects missing profiles, timeouts, uncertain cleanup, changed source, and duplicate database identities |
| Native SQL Server and vendor platform certification | NOT RUN · real SQL Server functionality ran in local Docker x86 emulation on ARM64, and vendor certification is NOT GRANTED |
| Graceful SQL Server shutdown and restart recovery | NOT RUN |
| Gradle, Spring Boot/JPA/MyBatis app, and performance verification | NOT RUN |
| Product redistribution | NOT GRANTED |

Phase 2 regression records the real database rows as NOT RUN. The live execution and verdict are recorded in separate G2 evidence. [Phase 2 regression](../../evidence/PHASE2-VALIDATION.json) · [Managed safety controls](../../evidence/G2-MANAGED-SAFETY.json) · [Evidence verifier](../../evidence/G2-EVIDENCE-VERIFIER-VALIDATION.json) · [Driver and execution policy](19-REAL-DB-G2.md)

## Reproduction

| Task | Command |
|---|---|
| Verify retained evidence against the working tree | `python3 tools/verify-real-g2.py` |
| Run the Phase 2 contract regression | `python3 tools/run-phase2.py` |
| Run new dedicated real databases | `python3 tools/run-managed-g2.py` |

Reproducing the real database run starts 4 new containers in sequence and retains the stopped containers and their data. Run the evidence verifier alone to check the retained evidence.

## Next phase

Phase 3 covers FR-005~007 with JPA/MyBatis/JdbcTemplate Observe adapters and a fingerprint event contract that excludes sensitive values. It also checks flush, cache, and rollback compatibility on the same DataSource. Rewrite remains disabled by default and Core stays independent of Spring. [Requirements traceability](16-TRACEABILITY.md)
