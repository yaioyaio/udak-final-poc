# Release decision and support evidence

English | [한국어](../ko/30-RELEASE-SUPPORT-EVIDENCE.md)

**Formal release is BLOCKED.** G0 is approved for the UDAK-owned source and six thin `0.1.0-poc` packages. The approved G5 pilot passed on the two native fixtures. Product support and full G5 certification remain open. The original G6 candidate records `authorize_publish=false`. [Approved scope and pilot results](31-RELEASE-APPROVAL-SCOPE.md) · [Original gate report](../../evidence/PHASE6-GATE.json)

## G0 licensing scope

1. The rights holder approved Apache-2.0 and commercial distribution for the recorded version and six-module scope. The distribution destination and publishing authority require a separate decision. [Scope decision](../../evidence/RELEASE-G0-G5-DECISION.json)
2. The approval excludes external binaries. The Boot POM and BOM consumer graphs differ. The local SBOM records 29 external artifacts across those graphs and tests so they can be reviewed separately from bundled contents. [Candidate graphs and packages](24-STARTERS-CLI-RELEASE-GATES.md)
3. The parser adapter selects Apache-2.0 from the upstream license options for JSqlParser 5.4. Its pinned POM declares only test dependencies. For redistribution under Apache-2.0, include the license, retain applicable notices, mark modified files and reproduce applicable NOTICE attribution when supplied. The decision applies to this component. [Pinned parser review](17-SQL-ENGINE-EVALUATION.md) · [Apache License §4](https://www.apache.org/licenses/LICENSE-2.0)
4. The JDBC drivers are validation dependencies. If the distribution includes them, review PostgreSQL's BSD-2-Clause and shaded notices, SQL Server's MIT text, MySQL's GPLv2 and Universal FOSS Exception, and the Oracle binary's FDHUT terms and applicable agreements. Reconcile transitive items including checker-qual (MIT) and protobuf-java (BSD-3-Clause). Review server licensing separately. [Pinned drivers and original texts](19-REAL-DB-G2.md) · [Oracle JDBC terms](https://download.oracle.com/otn-pub/otn_software/jdbc/FDHUT_LICENSE.txt)

## Verified database scope

| Fixture scope | Retained result | Limits |
|---|---|---|
| PostgreSQL 17.12 / JDBC 42.7.14, MySQL 8.4 / 26.10.0, SQL Server 2022 / 13.6.2.jre11, Oracle Database Free / ojdbc17 23.26.4.0.0 | Reverified the archived 40 minimal CRUD and transaction checks, 40 Observe scenarios and 32 approved rewrite checks across four pinned images. | SQL Server ran under x86 emulation. Native SQL Server and broader edition/version/platform support require separate evidence. |
| PostgreSQL 17.11 / JDBC 42.7.14 and MySQL 8.0.46 / 26.10.0 | Five new persistent approval cases per pair passed. Both produced the same page result as the executed PostgreSQL source. Each pair also retains two schema-query and three cancellation or recovery cases. | New approval cases on SQL Server and Oracle, pool behavior and recovery from unknown commit outcomes are NOT RUN. |

[Image pins](../../tools/g2-server-images.json) · [G2 results](20-MANAGED-G2-RESULTS.md) · [Observe](21-LEGACY-OBSERVE-RESULTS.md) · [G4](23-SELECTIVE-REWRITE-RESULTS.md) · [Recovery fixtures](28-DB-CANCELLATION-RECOVERY.md)

## Initial G5 execution plan

| Area | Limits and observations |
|---|---|
| Targets | Disposable PostgreSQL 17.11/JDBC 42.7.14 and MySQL 8.0.46/Connector/J 26.10.0. Run one database at a time and preserve all 12 existing containers. |
| Work | At most two operations in flight, four starts per second, and 48 operations per database. Observe completion, failure, commits and rollbacks of prepared reads and single-row writes on a small fixed fixture. |
| Resources | Up to 48 owned PIDs per database, 1 GiB process-tree RSS, 768 MiB of database scratch and 90 CPU seconds per process. Bound the test JVM to a 256 MiB heap and two active CPUs. |
| Time and cleanup | Stop at five minutes overall or 60 seconds for database startup. Confirm the owned loopback listener and connection health before starting. Stop on limit breaches or errors and verify owned-process termination and temporary file cleanup. |
| Outcome | Record observations, the exact execution environment, completion and failure counts, and cleanup. Limit the initial result to the tested pairs. Product certification requires approved performance criteria and additional database and platform evidence for concurrency, pools, cancellation and recovery. |

The operator approved this plan for one run, which passed. The product G5 document records the Observe performance criterion, real-DB pool results and the remaining authorization, platform and failure cases. Prior cancellation and pre-commit recovery results remain functional evidence. [Approved scope](31-RELEASE-APPROVAL-SCOPE.md) · [Product G5 criteria](32-PRODUCT-G5-ACCEPTANCE.md) · [Pilot execution](../../evidence/RELEASE-G5-PILOT.json) · [Existing recovery report](../../evidence/DB-RECOVERY-VALIDATION.json)

## Local acceptance and publisher authority

| Requirement | Acceptance evidence |
|---|---|
| RELEASE-001 | PASS. JDK 17.0.10 and Gradle 8.14.3 built the full Boot 3.5.16 demo. Two mixed access tests passed on H2 2.3.232. The packaged application ran its query and rollback paths and closed its pool. [Demo execution](../../evidence/RELEASE-DEMO-VALIDATION.json) |
| RELEASE-002 | PASS for the specified new cases and evidence review. Both native instances stopped and their scratch was reclaimed. Product support remains NOT CERTIFIED. [New live checks](../../evidence/RELEASE-SUPPORT-APPROVAL.json) · [Support matrix](../../evidence/RELEASE-SUPPORT-MATRIX.json) |
| RELEASE-003 | PASS for offline verification. A disposable OpenPGP key signed a test JAR and its manifest. Both detached signatures verified and both modified inputs were rejected. The formal publication gate returned BLOCKED. [Signing and gate evidence](../../evidence/RELEASE-SIGNING-VALIDATION.json) |

Run the local checks from the repository root. The demo command needs a JDK 17 installation, the live approval check needs the documented native providers on macOS arm64, and the signature check needs GnuPG.

```bash
python3 tools/run-release-demo.py --jdk17 /path/to/jdk-17
python3 tools/run-release-support.py
python3 tools/run-release-signing.py
python3 tools/run-release-support-matrix.py
```

To reproduce the formal decision from the repository root, run `python3 tools/release-gate.py --format json`. With valid inputs, expect `status=BLOCKED`, `authorize_publish=false` and exit 2. Exit 1 indicates invalid or unavailable gate input. The gate also treats a supplied approvals file as unverified. [Decision implementation](../../udak-cli/udak_cli.py) · [Requirement status](16-TRACEABILITY.md)

External publication requires the owner to approve a specific destination, namespace, coordinates, version and authorized publisher. Record G0 approval and G5 evidence before implementing a publisher for that target. If the owner selects Maven Central, verify namespace control, POM metadata, sources, Javadoc, checksums and GPG/PGP signatures against its requirements. The local test signature exercises verification only. Current policy records `formal_publisher=NOT IMPLEMENTED` and `publication_authority=NONE`. External publication is **NOT RUN**. [Central requirements](https://central.sonatype.org/publish/requirements/) · [Namespace registration](https://central.sonatype.org/register/namespace/)
