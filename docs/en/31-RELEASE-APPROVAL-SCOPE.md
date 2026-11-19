# Release approval scope proposal

English | [한국어](../ko/31-RELEASE-APPROVAL-SCOPE.md)

The rights holder's G0 decision and the operator's G5 execution approval are pending. Formal release is **BLOCKED** (`authorize_publish=false`). G0 is **NOT GRANTED**, G5 is **NOT RUN**, and product support is **NOT CERTIFIED**. [Release gates and support evidence](30-RELEASE-SUPPORT-EVIDENCE.md)

## G0 project license and distribution (RELEASE-004)

The proposal applies Apache-2.0 to UDAK-owned source intended for public release and retains applicable third-party notices. It requests commercial use approval within the reviewed scope for version `0.1.0-poc`, covering the six thin Maven packages `core`, `udak-api`, `jdbc-spring`, `observe-core`, `starter-boot3`, and `starter-boot4` under `dev.udak`. Binary distribution excludes JDBC drivers, database images, test harnesses, external binary JARs, and the fat demo JAR.

The review covers 30 module files for binary JARs, POMs, Gradle metadata, sources JARs and Javadoc JARs, plus five files including the SBOM, NOTICE and checksums. The 29 external dependencies across consumer and test graphs are tracked separately from bundled contents. The Maven list excludes `approval-history` and the standalone `rewrite-*` modules. Record the UDAK-owned public source scope and applicable third-party notices in the rights holder's decision. After approval, prepare LICENSE, NOTICE and POM license metadata, rebuild the candidate and verify the contents. Obtain separate approval for the publication destination, namespace, coordinates, version and authorized publisher. [Candidate packages and dependency graphs](24-STARTERS-CLI-RELEASE-GATES.md) · [Apache-2.0 text](https://www.apache.org/licenses/LICENSE-2.0) · [Central publication requirements](https://central.sonatype.org/publish/requirements/)

## G5 bounded native database run (RELEASE-005)

| Area | Proposed limits |
|---|---|
| Targets | Disposable native PostgreSQL 17.11 / JDBC 42.7.14 and MySQL 8.0.46 / Connector/J 26.10.0. Use loopback only. Run one database at a time, avoiding production endpoints and preserving all 12 retained containers. |
| Work | Per database, at most 2 operations in flight and 48 starts. Space starts at least 250 ms apart, with at most 4 in any rolling second. Observe completion, failures, commits, and rollbacks for prepared reads and single-row writes on a small fixed fixture. |
| Time | Up to 300 seconds overall, 60 seconds per native database startup, and 150 seconds per database server lifetime. |
| Resources | Per database, at most 48 owned PIDs and 1 GiB RSS across the owned process tree, 768 MiB of database scratch space, and 90 CPU seconds per process. Cap the client JVM at 256 MiB heap and 2 active CPUs, and child logs at 16 MiB. |
| Health and cleanup | Confirm ownership of the loopback listener and connection health before sending work. Stop on errors or limit breaches and verify termination of owned processes and cleanup of temporary files. |
| Evidence | Record the exact execution environment, measurements, completion and failure counts, and cleanup status. Limit any outcome to the tested combinations. |

The operator's decision covers one run within these limits. Product performance acceptance thresholds remain unresolved. Certification also requires concurrency, pool, cancellation, and recovery evidence from additional database and platform combinations. [Existing G5 plan](30-RELEASE-SUPPORT-EVIDENCE.md#initial-g5-execution-plan) · [Prior functional recovery evidence](../../evidence/DB-RECOVERY-VALIDATION.json)

## Verify the approval scope

Run `python3 -B tools/verify-release-approval-scope.py` from the repository root to reconcile the proposed artifact scope, native database and driver combinations, and resource limits with retained evidence. The scope check and Core smoke passed. The publication gate returned exit code 2 with verified historical evidence and a blocked release. The verification receipt records both decisions as PENDING. [Machine-readable proposal](../../tools/phase6-approval-scope.json) · [Verification receipt](../../evidence/RELEASE-APPROVAL-SCOPE.json)
