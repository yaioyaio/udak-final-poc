# Release approval scope

English | [한국어](../ko/31-RELEASE-APPROVAL-SCOPE.md)

G0 is **APPROVED** for the Apache-2.0 scope below. The initial bounded G5 pilot **PASS** applies to that run. Product G5 and formal release are **BLOCKED** (`authorize_publish=false`), and product support is **NOT CERTIFIED**. [Release gates and support evidence](30-RELEASE-SUPPORT-EVIDENCE.md) · [Approval decision](../../evidence/RELEASE-G0-G5-DECISION.json)

## G0 project license and distribution (RELEASE-004)

The approval applies Apache-2.0 to UDAK-owned source intended for public release and retains applicable third-party notices. It covers commercial use within the reviewed scope for version `0.1.0-poc`, covering the six thin Maven packages `core`, `udak-api`, `jdbc-spring`, `observe-core`, `starter-boot3`, and `starter-boot4` under `dev.udak`. Binary distribution excludes JDBC drivers, database images, test harnesses, external binary JARs, and the fat demo JAR.

The review covers 30 module files for binary JARs, POMs, Gradle metadata, sources JARs and Javadoc JARs, plus five files including the SBOM, NOTICE and checksums. The 29 external dependencies across consumer and test graphs are tracked separately from bundled contents. The Maven list excludes `approval-history` and the standalone `rewrite-*` modules. The candidate must include LICENSE, NOTICE and Maven POM license metadata. Candidate verification checks these files and the contents of the rebuilt packages. The production publication destination, namespace, coordinates, version and publishing authority require separate approval. [Candidate packages and dependency graphs](24-STARTERS-CLI-RELEASE-GATES.md) · [Apache-2.0 text](https://www.apache.org/licenses/LICENSE-2.0) · [Central publication requirements](https://central.sonatype.org/publish/requirements/)

The licensed candidate build passed. It reproduced the 30 original package hashes, then verified Apache-2.0 metadata in six POMs and LICENSE and NOTICE in all 18 JARs. The existing archive entries, dependency graph and module checksums were verified. The build reclaimed the disposable repository after validation. [Licensed candidate evidence](../../evidence/RELEASE-G0-CANDIDATE.json)

## Formal publication proposal (RELEASE-034)

The following choices are **PENDING** owner approval. The proposal uses the current G0 scope and the existing POC version.

| Decision | Proposal and evidence required |
|---|---|
| Destination and method | Use Maven Central via the Central Publisher Portal. After Portal validation, an authorized publisher manually confirms publication. Obtain owner approval for the destination and method. |
| Namespace | Keep `dev.udak` if control and Portal authorization can be verified. If the owner selects a different namespace, review the resulting coordinates and affected consumer metadata against G0 before rebuilding. |
| Release coordinates | Approve `dev.udak:core:0.1.0-poc`, `dev.udak:udak-api:0.1.0-poc`, `dev.udak:jdbc-spring:0.1.0-poc`, `dev.udak:observe-core:0.1.0-poc`, `dev.udak:starter-boot3:0.1.0-poc`, and `dev.udak:starter-boot4:0.1.0-poc` as POC coordinates. Confirm the version is available on the selected registry before publication. |
| Authority and signing | Designate the release approver, production signing operator and Portal publisher. Record the authorized namespace, coordinates and candidate revision in the approval. Grant one-time permission to upload and publish only after the required checks pass. Keep credentials and signing keys outside the repository. |

The proposal relies on the Portal's verified namespace and manual publication flow. Match the candidate to the selected target's metadata, sources, Javadoc, checksum and detached-signature requirements before submission. [Central namespace verification](https://central.sonatype.org/register/namespace/) · [Central publication requirements](https://central.sonatype.org/publish/requirements/) · [Central Portal validation and publication](https://central.sonatype.org/publish/publish-portal-guide/)

The release candidate review must tie the build inputs and archive hashes to one approved commit, verify the 30 module files and five supporting files, and compare contents to the G0 exclusions above. Formal publication also requires a verified production signature, product G5 PASS, a target-specific publication path, and an explicit publishing decision for the candidate. The offline check records the current gate denial and links each remaining prerequisite to its evidence. [Offline gate verification](30-RELEASE-SUPPORT-EVIDENCE.md#release-034-offline-publication-gate-verification)

## G5 bounded native database run (RELEASE-005)

| Area | Approved limits |
|---|---|
| Targets | Disposable native PostgreSQL 17.11 / JDBC 42.7.14 and MySQL 8.0.46 / Connector/J 26.10.0. Use loopback only. Run one database at a time, avoiding production endpoints and preserving all 12 retained containers. |
| Work | Per database, at most 2 operations in flight and 48 starts. Space starts at least 250 ms apart, with at most 4 in any rolling second. Observe completion, failures, commits, and rollbacks for prepared reads and single-row writes on a small fixed fixture. |
| Time | Up to 300 seconds overall, 60 seconds per native database startup, and 150 seconds per database server lifetime. |
| Resources | Per database, at most 48 owned PIDs and 1 GiB RSS across the owned process tree, 768 MiB of database scratch space, and 90 CPU seconds per process. Cap the client JVM at 256 MiB heap and 2 active CPUs, and child logs at 16 MiB. |
| Health and cleanup | Confirm ownership of the loopback listener and connection health before sending work. Stop on errors or limit breaches and verify termination of owned processes and cleanup of temporary files. |
| Evidence | Record the exact execution environment, measurements, completion and failure counts, and cleanup status. Limit any outcome to the tested combinations. |

The approval covers one run within these limits. The current product criteria and the status of concurrency, pool, cancellation, and recovery coverage are tracked in the product G5 evidence. [Existing G5 plan](30-RELEASE-SUPPORT-EVIDENCE.md#initial-g5-execution-plan) · [Product G5 criteria](32-PRODUCT-G5-ACCEPTANCE.md) · [Prior functional recovery evidence](../../evidence/DB-RECOVERY-VALIDATION.json)

## G5 pilot result

| Database / driver | Started / completed | Read / commit / rollback | Independent checks | Errors | Peak in flight | Peak starts per rolling second | p50 / p95 / max (µs) |
|---|---:|---:|---:|---:|---:|---:|---:|
| PostgreSQL 17.11 / JDBC 42.7.14 | 48 / 48 | 16 / 16 / 16 | 48 | 0 | 2 | 4 | 527 / 1,015 / 1,406 |
| MySQL 8.0.46 / Connector/J 26.10.0 | 48 / 48 | 16 / 16 / 16 | 48 | 0 | 2 | 4 | 1,087 / 3,379 / 12,196 |

The latencies describe prepared JDBC work and transaction outcomes for this pilot, excluding workload pacing and intentional synchronization. Both temporary native servers stopped and their scratch files were reclaimed automatically. This run consumed the single G5 approval. Another run requires separate approval. Product performance and support certification remain pending. [G5 pilot evidence](../../evidence/RELEASE-G5-PILOT.json)

## Predecessor proposal evidence

The predecessor proposal used `python3 -B tools/verify-release-approval-scope.py` to reconcile the candidate scope, native database and driver combinations, and resource limits with retained evidence. The scope check and Core smoke passed. The publication gate verified the historical evidence and returned exit code 2 with the release blocked. Its receipt records PENDING for both decisions at the time of the proposal. [Machine-readable proposal](../../tools/phase6-approval-scope.json) · [Verification receipt](../../evidence/RELEASE-APPROVAL-SCOPE.json)
