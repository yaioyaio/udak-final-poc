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

## RELEASE-034 offline publication gate verification

On the `develop` source revision `3a5026e`, `python3 -B tools/release-gate.py --format json` returned exit `1`, `BLOCKED`, `authorize_publish=false` and `HASH_MISMATCH`. Five checked-in Observe source and contract-test files differed from the retained Phase 6 source hashes. The harness, configuration and manifest hashes matched. The gate stopped at input verification before checking candidate binaries. The offline verification **passed** by reproducing that denial, confirming the approved G0 coordinates and reproducing the existing product G5 verdict. Seven synthetic CLI cases passed, including valid-input denial, unauthorized self-attestation and tampered input rejection. The publication checks used Python only. The separate guarded Core smoke test passed and its temporary files were cleaned up. Release builds, DB and container starts, and artifact registry uploads were zero. [Offline verification receipt](../../evidence/RELEASE-PUBLICATION-OFFLINE.json)

| Prerequisite | Current status and next action |
|---|---|
| Destination, namespace, coordinates, version and authority | **PENDING**. Decide the proposed registry, verify the approved namespace, confirm the six coordinates and assign the authorized roles. [Formal publication proposal](31-RELEASE-APPROVAL-SCOPE.md#formal-publication-proposal-release-034) |
| Approved G0 scope and fresh candidate evidence | G0 is **APPROVED** for the six modules. The gate's fixed historical license values belong to its original policy. In an eligible environment, build the selected commit and record fresh input and package hashes. Verify that the new evidence matches that candidate before rerunning the gate. [G0 decision](../../evidence/RELEASE-G0-G5-DECISION.json) |
| Product G5 and DB support | **BLOCKED / NOT CERTIFIED**. Current-candidate PostgreSQL and MySQL functional evidence is refreshed. Observe p95 for both profiles on the current candidate, current Oracle evidence and instance checks, and native SQL Server evidence remain open. [Prior product G5 decision](../../evidence/PRODUCT-G5-ACCEPTANCE.json) |
| Production signing and publisher | Production signing is **NOT RUN**. The formal publisher is `NOT IMPLEMENTED` and publication authority is `NONE`. Verify the production signature and target-specific flow before requesting a final publication decision for the exact candidate. |

## RELEASE-035 public registry and namespace check

The 2026-11-20 check queried the exact public Maven Central POM and version paths for the six G0-approved GAVs. All twelve paths returned HTTP 404, and both positive control paths returned HTTP 200. The public DNS check returned `NXDOMAIN` for `udak.dev`. Portal verification and publisher access are **UNVERIFIED**, and the final registry decision and role assignments are **PENDING**. The check made zero registry uploads or namespace changes. The release gate remains **BLOCKED**. [Registry check receipt](../../evidence/RELEASE-PUBLICATION-REGISTRY-CHECK.json) · [Publication role assignments](31-RELEASE-APPROVAL-SCOPE.md#registry-check-and-publication-roles-release-035)

## RELEASE-036 alternative publication namespace

All twelve public Maven Central POM and version paths for `io.github.yaioyaio.udak` returned HTTP 404. Both positive control paths returned HTTP 200. The offline G0 comparison checked six artifact IDs, the `0.1.0-poc` version and the package inventory of 30 module files and five supporting files. Applying the group change in memory mapped ten internal POM references and preserved nine external POM declarations. The new group requires a G0 scope decision and verified Portal rights. Release builds, namespace changes and artifact uploads were zero. The release gate is **BLOCKED**. [Alternative comparison receipt](../../evidence/RELEASE-PUBLICATION-ALTERNATIVE.json) · [Approval and implementation conditions](31-RELEASE-APPROVAL-SCOPE.md#github-based-namespace-alternative-release-036)

## RELEASE-021 readiness

| Check | Result |
|---|---|
| macOS and existing Parallels guest | The arm64 Mac had 16 physical cores and 64 GiB RAM. The recorded macOS memory-pressure level was 2, so the full local rehearsal remains pending normal host conditions. The existing arm64 Ubuntu guest was suspended with 2 vCPUs and 4 GiB configured. The check used configuration only and guest engine and storage remain UNVERIFIED. [Host evidence](../../evidence/RELEASE-READINESS-HOST.json) |
| Native SQL Server target | BLOCKED on the selected ARM host and guest. Microsoft supports SQL Server Linux container images on Intel or AMD x86-64 Linux hosts. Native SQL Server G5 is NOT RUN. [Microsoft platform requirements](https://learn.microsoft.com/en-us/sql/linux/containers/deploy?view=sql-server-ver16) |
| Oracle storage prerequisite | The existing local Linux Docker engine reported arm64, cgroup v2 and `overlayfs`. The bounded Oracle profile requires `overlay2` on XFS mounted with project quotas for its per-container writable-layer size limit. Quota acceptance and the Oracle instance G5 trial are NOT RUN. [Host evidence](../../evidence/RELEASE-READINESS-HOST.json) · [Docker storage options](https://docs.docker.com/reference/cli/docker/container/run/#set-storage-driver-options-per-container) |
| Local checks and remaining rehearsal | Core smoke passed. The signing check used disposable OpenPGP signatures on a synthetic ZIP and its manifest. Both verified and both modified inputs were rejected. Cleanup passed and the temporary agent stopped. The build of the six previously approved thin modules and verification of their real release bundle remain NOT RUN. This includes the 30 package files recorded for the earlier G0 candidate. [Signing evidence](../../evidence/RELEASE-READINESS-SIGNING-SMOKE.json) · [Earlier candidate](../../evidence/RELEASE-G0-CANDIDATE.json) |
| Publication decision | The rehearsal records the checked-out commit as the source revision and validates the checkout's publication veto. The 2026-11-20 signing smoke used `34dac41` and observed `HASH_MISMATCH` on the earlier G6 evidence. The current and historical decisions both report `authorize_publish=false`. Formal publisher, destination and publication authority are pending. [Signing and gate evidence](../../evidence/RELEASE-READINESS-SIGNING-SMOKE.json) |

The approved G0 scope and prior G5 decisions remain in effect. The readiness check recorded zero VM resumes, database starts, and container starts. External deployment and publication are **NOT RUN**. [Host evidence](../../evidence/RELEASE-READINESS-HOST.json) · [Approved scope](31-RELEASE-APPROVAL-SCOPE.md) · [Product G5 criteria](32-PRODUCT-G5-ACCEPTANCE.md)

### Current environment and resume conditions

The initial read-only check on 2026-11-24 found Mac memory pressure at level 2. A subsequent check showed level 1 with about 592 MiB of free swap. The ARM Ubuntu Parallels guest was suspended with two vCPUs and 4 GiB, and the Mac's Docker engine used `overlayfs`. The native SQL Server host check returned `HOST_LINUX_X86_64`. There were zero DB, VM, or container starts and zero new performance measurements.

An earlier reassessment stopped at a pool evidence input hash mismatch. With memory pressure at level 1, the subsequent refresh ran 16 PostgreSQL and MySQL functional cases sequentially and updated four evidence files for the current inputs. All temporary native databases and workspace files were reclaimed. No VM or container started. A full product G5 reassessment verified the four updated reports and the prior Observe baseline, then stopped at the input hash mismatch in the Oracle pool proof. The prior product decision retains its revision scope. [Functional evidence refresh](32-PRODUCT-G5-ACCEPTANCE.md#current-candidate-postgresql-and-mysql-functional-evidence)

Current Observe functional contracts passed under `OBSERVE-G5-FOLLOWUP`. One-run approval and pinned inputs were verified. The official p95 test is **NOT RUN** because the 2026-11-24 preflight stayed at memory pressure level 2. Resume under the same ID and unused approval once the host is stable. Resume Oracle and SQL Server under the dedicated environment conditions below. [One-run approval](../../evidence/PRODUCT-G5-PERFORMANCE-OBSERVE-G5-FOLLOWUP-APPROVAL.json) · [Product G5 criteria](32-PRODUCT-G5-ACCEPTANCE.md)

On 2026-11-20 the observable Mac memory pressure was level 2 and the existing ARM Ubuntu guest was suspended. The full rehearsal command returned `HOST_MEMORY_PRESSURE` before Gradle started. The checked-out source and approved scope checks, synthetic signing, and publication veto passed. The readiness check started zero VMs, DB servers or containers.

| Work | Disposition and resume condition |
|---|---|
| Six-module package and real-bundle rehearsal | **Deferred, NOT RUN.** After macOS memory pressure returns to level 1 and no heavy workload overlaps, run `python3 -B tools/release-provider/run-local-release-rehearsal.py` from the approved candidate checkout. The runner snapshots the committed source and records its revision. It checks memory before preparing the build and again before Gradle, with one Gradle worker and a 600-second wall-clock limit. [Local runner](../../tools/release-provider/run-local-release-rehearsal.py) |
| Oracle instance concurrency and crash recovery | **Deferred, NOT RUN.** After both Observe p95 profiles pass and Mac memory pressure normalizes, preserve the existing Ubuntu ARM64 guest session and check its dedicated test capacity. In the guest, use `python3 -B tools/release-provider/check-oracle-guest.py` to check available memory, the isolated Docker engine, and XFS project quota prerequisites. The existing 4 GiB allocation leaves no guest OS overhead. Use the protected Oracle runner after the guest check passes and the exact trial is approved. [Guest check and limits](32-PRODUCT-G5-ACCEPTANCE.md#oracle-instance-test-and-local-guest-readiness-release-014-release-026) · [Oracle runner](../../tools/release-provider/run-oracle-instance.py) |
| Native SQL Server G5 | **Blocked on this Mac and Parallels, NOT RUN.** Parallels runs Intel guests on Apple silicon through emulation. Microsoft requires Intel or AMD x86-64 Linux and excludes emulation from support for the SQL Server Linux container. Resume on an approved dedicated native x86-64 Linux host. Check the native host, local Docker capacity, and pinned image with `python3 -B tools/release-provider/check-sqlserver-host.py` before scheduling G5. [Microsoft platform requirements](https://learn.microsoft.com/en-us/sql/linux/containers/deploy?view=sql-server-ver16) · [Parallels x86 emulator](https://kb.parallels.com/en/130217) |
| Formal publication | **Blocked, NOT RUN.** Resume after G5 is accepted, the release gate is verified against current evidence, production signing is available, and the publication destination, namespace and authority are approved and configured. A successful local rehearsal supplies package and test-signing evidence for the release review. The recorded gate decision is `authorize_publish=false`. |
