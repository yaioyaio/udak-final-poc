# Phase 6 Starters, CLI and Release Gates

English | [한국어](../ko/24-STARTERS-CLI-RELEASE-GATES.md)

Phase 6 covers FR-017, T-018, T-019, T-020 and the read-only CLI portion of T-021. MCP remains follow-up work. Local CI and the G6 private-candidate gate are PASS; formal release is BLOCKED. [Traceability](16-TRACEABILITY.md)

## Separate Spring Boot Starters

| Local candidate coordinate | Target runtime |
|---|---|
| `dev.udak:starter-boot3:0.1.0-poc` | Spring Boot 3.5.16 / Spring Framework 6.2.19 |
| `dev.udak:starter-boot4:0.1.0-poc` | Spring Boot 4.1.2 / Spring Framework 7.0.10 |

Use the Starter that matches the application's Boot major version. Boot discovers it through `AutoConfiguration.imports`. A startup guard rejects both Starters on one classpath and rejects a Starter on the wrong Boot major, including when `udak.enabled=false`. The defaults enable the Observe configuration with a `SqlObserver` and a no-op `ObservationSink`. Applications can provide their own observer or sink. Hook registration for Hibernate, MyBatis and JDBC remains explicit. Rewrite stays `DENY` and attempts to enable it fail at startup. [Configuration keys](11-API-CONFIG-SCHEMA.md)

The optional lazy `SpringJdbcExecutor` requires `udak.jdbc.enabled=true`, an explicit `DbVendor` and exactly one `DataSource` bean. The application can supply its own `SqlExecutor`. With multiple data sources, marking one `@Primary` still leaves the executor unconfigured. The executor participates in a Spring transaction on that data source.

## Protected Local Validation

```bash
python3 tools/local-ci.py
# Individual steps:
python3 tools/run-phase6.py
python3 tools/test-phase6-verifier.py
python3 tools/verify-phase6.py
python3 tools/udak-cli.py inspect --format json
python3 tools/release-gate.py
```

The protected harness uses JDK 17 or later, Python 3, Gradle 8.14.3 and downloads from the pinned Gradle distribution and Maven Central. The independent Gradle build under `starter-testkit/` packages the Starters and required UDAK modules. Its consumer applications resolve the candidate JARs through Maven POM metadata. Each line covers 11 regular application scenarios including an actual H2 rollback with an externally supplied transaction. A separate matrix covers 1 mixed-Starter and 2 wrong-Boot-major rejections. Local CI uses `tools/local-ci.py`. GitHub Actions is prohibited.

The harness limits total wall time to 1,800 seconds and Gradle to a 512 MiB heap, 256 MiB metaspace, 2 active CPUs and 1 worker. Consumer JVM heap is capped at 256 MiB. Workspace and candidate limits are 2 GiB / 20,000 files and 200 MiB / 500 files respectively. Phase 6 uses embedded H2, creates 0 containers and preserves the 12 previously stopped DB containers.

The verifier checks the existing candidate and its evidence. The read-only CLI inspects designated local validation evidence and checks its hashes. It does not access application configuration, SQL, databases or the network.

## Candidate and Formal Release

Local packaging produces a private evaluation candidate. The G6 local review covers package metadata, checksums, SBOM, NOTICE and version/API compatibility evidence. Formal release remains `BLOCKED` with exit code `2`. It requires approval of UDAK's own license and the G0 commercial licensing decision, G5 concurrency/performance/cancellation/recovery evidence, and an authorized, implemented publisher. External publication and product support certification remain NOT RUN. [Validation gates](08-TEST-VALIDATION.md)

Official references. [Boot 3.5 requirements](https://docs.spring.io/spring-boot/3.5/system-requirements.html), [Boot 4.1 requirements](https://docs.spring.io/spring-boot/4.1/system-requirements.html), [Spring Boot auto-configuration](https://docs.spring.io/spring-boot/reference/features/developing-auto-configuration.html), [Maven Central publishing requirements](https://central.sonatype.org/publish/requirements/).

The fixture applications exclude Boot DataSource, transaction-manager and JdbcTemplate auto-configuration and disable SQL initialization to isolate UDAK behavior. In service applications, Boot or user beans may initialize a DataSource. Java 17 is the compilation target; execution evidence records the actual JDK.

Dependencies freeze the actual Gradle project and standalone POM consumer graphs separately. Boot 4 POM consumers select Commons Logging 1.3.5 and Micrometer 1.16.8; Boot BOM consumers select 1.3.6 and 1.17.2. Both use Boot 4.1.2 / Spring 7.0.10. An additional BOM consumer application is tested, and the union of 29 external artifacts is recorded in the SBOM.

## Actual validation results

| Check | Result |
|---|---|
| Boot 3 POM / Boot 4 POM / Boot 4 BOM | Each: 11 scenarios and 79 assertions PASS |
| Mixed Starters / two wrong-major combinations | Each: 3 assertions, startup refusal PASS |
| CLI contracts / verifier mutation and safety contracts | 41 / 50 PASS, skipped 0 |
| Package reproducibility / distribution evidence | 30 identical JAR/POM/module/sources/Javadoc files; 35 including SBOM metadata |
| Existing public API / Core regression | 22 existing sources preserved; Core smoke PASS |
| Successful build automatic cleanup | 2,351 files / 375,381,725 bytes; zero remaining |
| Synthetic failure / timeout / interruption probes | Each: one owned output file / zero bytes removed; zero remaining |

Execution used JDK 21.0.13 / Gradle 8.14.3 and generated Java 17 class files. The harness accepts JDK 17–24. [Execution report](../../evidence/PHASE6-VALIDATION.json), [50 verifier tests](../../evidence/PHASE6-VERIFIER-VALIDATION.json), [local CI](../../evidence/PHASE6-LOCAL-CI.json), [G6 candidate gate](../../evidence/PHASE6-GATE.json).

Candidate JAR/POM files and dedicated caches are automatically removed after checking, so the CLI reports `candidate_artifacts=NOT AVAILABLE`. This is distinct from validation of preserved execution evidence. `tools/local-ci.py` regenerates and checks the candidate from the same inputs. Sanitized failed execution reports are preserved under `.git/`; unknown material is preserved. Twelve existing stopped databases were retained.

## Next work

Finalize product acceptance criteria and validate the remaining G5 and DB support scenarios. The expansion verified the full legacy demo on an actual JDK 17, disposable local OpenPGP signatures and the one approved G5 pilot. Publication coordinates and authority, production signing, publication and full database support certification remain open. MCP is a separate follow-up. [Expansion results](30-RELEASE-SUPPORT-EVIDENCE.md) · [Approved G0 and G5 scope](31-RELEASE-APPROVAL-SCOPE.md)
