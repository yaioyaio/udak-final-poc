# 정식 배포 판단과 지원 근거

[English](../en/30-RELEASE-SUPPORT-EVIDENCE.md) | 한국어

**정식 배포는 BLOCKED다.** G0는 UDAK 소유 소스와 라이브러리 6종의 `0.1.0-poc` 배포 범위에 대해 승인됐다. 승인된 G5 1차 시험은 두 네이티브 DB에서 통과했다. 제품 지원과 G5 전체 인증은 남아 있다. 기존 G6 후보의 배포 허가 값은 `authorize_publish=false`다. [승인 범위와 시험 결과](31-RELEASE-APPROVAL-SCOPE.md) · [기존 게이트 결과](../../evidence/PHASE6-GATE.json)

## G0 라이선스 범위

1. 권리자가 기록된 버전과 라이브러리 6종 범위에 대해 Apache-2.0과 상업 배포를 승인했다. 배포 채널과 게시 권한은 별도 결정이 필요하다. [범위 승인 기록](../../evidence/RELEASE-G0-G5-DECISION.json)
2. 승인 범위에서 외부 바이너리 동봉은 제외한다. Boot POM 소비자와 BOM 소비자의 의존성 그래프는 다르다. 로컬 SBOM은 동봉 파일과 분리하여 두 그래프 및 테스트의 외부 아티팩트 29개를 기록한다. [후보 그래프 및 패키지](24-STARTERS-CLI-RELEASE-GATES.md)
3. 파서 어댑터는 JSqlParser 5.4의 라이선스 선택지 중 Apache-2.0을 채택했다. 고정한 POM에는 테스트 의존성만 선언되어 있다. Apache-2.0으로 재배포할 때는 라이선스를 제공하고 적용되는 고지를 유지하며 수정한 파일에 변경을 표시하고, 원본 NOTICE가 있으면 관련 표기를 제공한다. 이 결정의 적용 대상은 해당 파서다. [고정 파서 검토](17-SQL-ENGINE-EVALUATION.md) · [Apache 라이선스 제4절](https://www.apache.org/licenses/LICENSE-2.0)
4. JDBC 드라이버는 검증용 의존성이다. 배포물에 포함할 경우 PostgreSQL의 BSD-2-Clause와 내장 구성요소 고지, SQL Server의 MIT 원문, MySQL의 GPLv2와 Universal FOSS Exception, Oracle 바이너리의 FDHUT와 적용 계약을 검토한다. 전이 의존성 중 checker-qual(MIT), protobuf-java(BSD-3-Clause)도 대조한다. 서버 라이선스는 별도로 검토한다. [드라이버 고정 목록과 원문](19-REAL-DB-G2.md) · [Oracle JDBC 약관](https://download.oracle.com/otn-pub/otn_software/jdbc/FDHUT_LICENSE.txt)

## 검증된 데이터베이스 범위

| 검증 조합 | 보존된 결과 | 검증 한계 |
|---|---|---|
| PostgreSQL 17.12 / JDBC 42.7.14, MySQL 8.4 / 26.10.0, SQL Server 2022 / 13.6.2.jre11, Oracle Database Free / ojdbc17 23.26.4.0.0 | 고정 이미지 4종의 최소 CRUD·트랜잭션 40건, Observe 40건, 승인 변환 32건에 대한 기존 증거를 재검증했다. | SQL Server는 x86 에뮬레이션에서 실행했다. 네이티브 SQL Server 및 추가 에디션·버전·플랫폼의 지원 판단에는 별도 근거가 필요하다. |
| PostgreSQL 17.11 / JDBC 42.7.14 및 MySQL 8.0.46 / 26.10.0 | 조합별 승인 이력 5건이 새로 통과했다. 실행한 PostgreSQL 원본 쿼리와 두 DB의 페이지 결과가 일치했다. 조합별 스키마 쿼리 2건과 취소·복구 3건의 기존 증거도 확인했다. | SQL Server와 Oracle의 신규 승인 이력, 커넥션 풀, 커밋 결과 불명 복구는 NOT RUN이다. |

[이미지 고정 목록](../../tools/g2-server-images.json) · [G2 결과](20-MANAGED-G2-RESULTS.md) · [Observe](21-LEGACY-OBSERVE-RESULTS.md) · [G4](23-SELECTIVE-REWRITE-RESULTS.md) · [복구 시나리오](28-DB-CANCELLATION-RECOVERY.md)

## G5 1차 실행 계획

| 항목 | 한도와 확인 방법 |
|---|---|
| 대상 | 임시 PostgreSQL 17.11/JDBC 42.7.14, MySQL 8.0.46/Connector/J 26.10.0. 한 번에 DB 하나를 기동하고 기존 컨테이너 12개를 보존한다. |
| 작업량 | DB별 최대 동시 작업 2개, 초당 작업 시작 4건, 총 작업 48건. 작은 고정 fixture에서 준비된 조회와 단일 행 갱신의 성공, 종료, 커밋·롤백 결과를 관측한다. |
| 자원 | DB별 소유 프로세스 PID 최대 48개, 프로세스 트리 RSS 1 GiB, DB 임시 파일 768 MiB, 프로세스 CPU 90초. 검사 JVM 힙 256 MiB, 활성 CPU 2개. |
| 시간과 정리 | 전체 5분 상한, DB 시작 60초 상한. 소유 루프백 리스너와 연결 상태를 확인한 뒤 시작한다. 한도 초과·오류 시 시험을 종료하고 소유 프로세스 종료와 임시 파일 정리를 검사한다. |
| 판정 | 실측 값과 고정된 실행 환경, 완료·실패 건수, 정리 상태를 기록한다. 1차 결과는 해당 조합에 한정한다. 제품 인증에는 승인된 성능 기준과 추가 DB·플랫폼의 동시성·풀·취소·장애복구 증거가 필요하다. |

운영자가 승인한 1회 시험은 통과했다. 제품 G5 문서에 Observe 성능 기준, 풀 실DB 검증 결과, 남은 승인 및 플랫폼·장애 시나리오를 기록한다. 취소와 커밋 전 복구의 이전 기능 검증을 보존한다. [승인 범위](31-RELEASE-APPROVAL-SCOPE.md) · [제품 G5 기준](32-PRODUCT-G5-ACCEPTANCE.md) · [1차 시험 증거](../../evidence/RELEASE-G5-PILOT.json) · [기존 복구 증거](../../evidence/DB-RECOVERY-VALIDATION.json)

## 로컬 인수 기준과 배포 권한

| 요구 ID | 인수 근거 |
|---|---|
| RELEASE-001 | PASS. JDK 17.0.10과 Gradle 8.14.3으로 Boot 3.5.16 전체 데모를 빌드했다. H2 2.3.232에서 혼합 접근 테스트 2건이 통과했다. 패키지 앱의 조회·롤백 실행과 커넥션 풀 종료를 확인했다. [데모 실행](../../evidence/RELEASE-DEMO-VALIDATION.json) |
| RELEASE-002 | 지정한 신규 시나리오와 증거 재검증 PASS. 네이티브 DB 두 개를 종료하고 임시 파일을 회수했다. 제품 지원은 NOT CERTIFIED다. [신규 실DB 검증](../../evidence/RELEASE-SUPPORT-APPROVAL.json) · [지원 매트릭스](../../evidence/RELEASE-SUPPORT-MATRIX.json) |
| RELEASE-003 | 로컬 서명 검증 PASS. 일회용 OpenPGP 키로 테스트 JAR과 매니페스트에 분리 서명을 생성했다. 두 서명이 검증됐고 바이트를 변경한 두 입력은 거부됐다. 정식 게시 게이트는 BLOCKED다. [서명과 게이트 증거](../../evidence/RELEASE-SIGNING-VALIDATION.json) |

저장소 루트에서 실행한다. 데모에는 JDK 17 설치본이, 실DB 승인 확인에는 macOS arm64 네이티브 provider가, 서명 검사에는 GnuPG가 필요하다.

```bash
python3 tools/run-release-demo.py --jdk17 /path/to/jdk-17
python3 tools/run-release-support.py
python3 tools/run-release-signing.py
python3 tools/run-release-support-matrix.py
```

저장소 루트에서 `python3 tools/release-gate.py --format json`으로 정식 배포 판단을 재현한다. 유효한 입력의 기대 결과는 `status=BLOCKED`, `authorize_publish=false`, 종료 코드 2다. 종료 코드 1은 게이트 입력이 잘못됐거나 확인할 수 없다는 뜻이다. 승인 파일을 제공해도 게이트는 이를 미검증으로 처리한다. [판단 구현](../../udak-cli/udak_cli.py) · [요구별 상태](16-TRACEABILITY.md)

외부 배포를 위해 책임자는 대상 저장소, 네임스페이스, 좌표, 버전, 게시 권한자를 지정하고 승인해야 한다. G0 승인과 G5 근거를 기록한 뒤 해당 대상용 게시기를 구현한다. Maven Central을 선택하는 경우 네임스페이스 소유권, POM 메타데이터, 소스, Javadoc, 체크섬, GPG/PGP 서명을 Central 요건과 대조한다. 로컬 테스트 서명은 검증 동작만 확인한다. 현재 정책은 `formal_publisher=NOT IMPLEMENTED`, `publication_authority=NONE`이다. 외부 게시는 **NOT RUN**이다. [Central 게시 요건](https://central.sonatype.org/publish/requirements/) · [네임스페이스 등록](https://central.sonatype.org/register/namespace/)

## RELEASE-034 게시 게이트 오프라인 검증

`develop` 소스 리비전 `3a5026e`에서 `python3 -B tools/release-gate.py --format json`은 종료 코드 `1`, `BLOCKED`, `authorize_publish=false`, `HASH_MISMATCH`를 반환했다. 추적 중인 Observe 소스와 계약 테스트 파일 5개의 해시가 보존한 Phase 6 소스 해시와 달랐다. 하네스·구성·매니페스트 해시는 일치했다. 게이트는 후보 바이너리 검사에 앞서 입력 검증에서 중단했다. 해당 차단과 G0 승인 좌표, 기존 제품 G5 판정을 재현해 오프라인 검증은 **PASS**했다. 유효한 입력의 게시 차단, 자체 승인 거부, 변조 입력 차단을 포함한 CLI 합성 테스트 7건이 통과했다. 게시 검증에는 Python만 사용했다. 저장소 보호 실행기를 통한 별도 Core 스모크도 통과했고 임시 파일 정리를 확인했다. 릴리스 빌드, DB·컨테이너 기동, 아티팩트 저장소 업로드는 각각 0건이다. [오프라인 검증 기록](../../evidence/RELEASE-PUBLICATION-OFFLINE.json)

| 선행조건 | 현재 상태와 후속 조치 |
|---|---|
| 게시 대상·네임스페이스·좌표·버전·권한 | **PENDING**. 제안한 저장소를 결정하고 네임스페이스를 검증하며 6개 좌표와 담당 역할을 확정한다. [정식 게시 범위 결정안](31-RELEASE-APPROVAL-SCOPE.md#정식-게시-범위-결정안-release-034) |
| G0 승인 범위와 최신 후보 증거 | 모듈 6종의 G0는 **APPROVED**다. 게이트의 고정된 과거 라이선스 값은 초기 정책 값이다. 실행 가능한 환경에서 선택한 커밋을 빌드하고 입력·패키지 해시를 새로 기록한다. 해당 후보와 새 증거가 일치하는지 확인한 뒤 게이트를 재검증한다. [G0 승인 결정](../../evidence/RELEASE-G0-G5-DECISION.json) |
| 제품 G5와 DB 지원 | **BLOCKED / NOT CERTIFIED**. 현재 PostgreSQL·MySQL 기능 증거를 갱신했다. 두 DB의 공식 Observe p95가 상한을 초과했으며 Oracle 현재 증거·인스턴스 검증과 네이티브 SQL Server 증거가 남아 있다. [공식 성능 증거](../../evidence/PRODUCT-G5-PERFORMANCE-OBSERVE-G5-FOLLOWUP-RESULT.json) |
| 운영 서명과 게시기 | 운영 서명은 **NOT RUN**이다. 정식 게시기는 `NOT IMPLEMENTED`, 게시 권한은 `NONE`이다. 후보별 최종 게시 승인을 받기 전에 운영 서명과 대상 저장소의 게시 절차를 검증한다. |

## RELEASE-035 공개 저장소와 네임스페이스 조회

2026-11-20에 G0 승인 GAV 6개의 Maven Central 공개 POM과 버전 경로를 조회했다. 후보 경로 12개는 모두 HTTP 404, 대조군 경로 2개는 모두 HTTP 200을 반환했다. 공개 DNS에서 `udak.dev`는 `NXDOMAIN`으로 확인됐다. Portal 검증과 게시 권한은 **UNVERIFIED**이며, 최종 게시 대상과 담당자 지정은 **PENDING**이다. 아티팩트 업로드와 네임스페이스 변경은 각각 0건이다. 게시 게이트는 **BLOCKED**다. [공개 조회 기록](../../evidence/RELEASE-PUBLICATION-REGISTRY-CHECK.json) · [게시 담당 역할](31-RELEASE-APPROVAL-SCOPE.md#게시-대상-조회와-담당-역할-release-035)

## RELEASE-036 대체 게시 네임스페이스

`io.github.yaioyaio.udak`의 Maven Central 공개 POM과 버전 경로 12개는 모두 HTTP 404를 반환했다. 대조군 경로 2개는 모두 HTTP 200을 반환했다. 오프라인 G0 대조에서 모듈 ID 6개, 버전 `0.1.0-poc`, 모듈 파일 30개와 지원 파일 5개의 범위를 확인했다. 그룹 변경을 메모리에서 적용해 내부 POM 참조 10개를 매핑하고 외부 POM 선언 9개가 일치하는지 확인했다. 새 그룹에는 G0 범위 결정과 Portal 권한 확인이 필요하다. 릴리스 빌드, 네임스페이스 변경, 아티팩트 업로드는 각각 0건이다. 게시 게이트는 **BLOCKED**다. [대체 후보 비교 기록](../../evidence/RELEASE-PUBLICATION-ALTERNATIVE.json) · [승인과 구현 조건](31-RELEASE-APPROVAL-SCOPE.md#github-기반-대체-네임스페이스-release-036)

## RELEASE-021 릴리스 준비 상태

| 점검 항목 | 결과 |
|---|---|
| macOS와 기존 Parallels 게스트 | arm64 Mac은 물리 코어 16개와 RAM 64 GiB를 갖췄다. 검사 당시 macOS 메모리 압력 수준은 2였으며, 전체 로컬 리허설은 호스트 상태가 정상으로 돌아오면 진행할 수 있다. 기존 arm64 Ubuntu 게스트는 일시 중단 상태였으며 2 vCPU와 4 GiB로 설정돼 있었다. 구성만 확인했으며 게스트의 엔진과 저장소는 UNVERIFIED다. [호스트 증거](../../evidence/RELEASE-READINESS-HOST.json) |
| 네이티브 SQL Server 대상 | 선택한 ARM 호스트와 게스트에서는 BLOCKED다. Microsoft는 Intel 또는 AMD x86-64 Linux 호스트에서 SQL Server Linux 컨테이너 이미지를 지원한다. 네이티브 SQL Server G5는 NOT RUN이다. [Microsoft 플랫폼 요건](https://learn.microsoft.com/en-us/sql/linux/containers/deploy?view=sql-server-ver16) |
| Oracle 저장소 선행조건 | 기존 로컬 Linux Docker 엔진에서 arm64, cgroup v2, `overlayfs`를 확인했다. 자원 상한을 적용하는 Oracle 프로파일은 컨테이너별 쓰기 계층 용량 제한을 위해 프로젝트 쿼터가 설정된 XFS의 `overlay2`를 요구한다. 쿼터 적용과 Oracle 인스턴스 G5 시험은 NOT RUN이다. [호스트 증거](../../evidence/RELEASE-READINESS-HOST.json) · [Docker 저장소 옵션](https://docs.docker.com/reference/cli/docker/container/run/#set-storage-driver-options-per-container) |
| 로컬 검증과 남은 리허설 | Core 스모크가 통과했다. 서명 검사는 모의 ZIP과 매니페스트에 일회용 OpenPGP 키로 분리 서명을 만들었다. 두 서명 모두 검증됐고 변경된 입력 두 개는 거부됐다. 정리가 통과했고 임시 에이전트도 종료됐다. 승인된 thin 라이브러리 6종의 빌드와 실제 릴리스 번들 확인은 NOT RUN이다. 이전 G0 후보에 기록된 패키지 파일 30개도 이 검증 범위에 포함된다. [서명 증거](../../evidence/RELEASE-READINESS-SIGNING-SMOKE.json) · [이전 후보](../../evidence/RELEASE-G0-CANDIDATE.json) |
| 게시 판정 | 리허설은 체크아웃한 커밋을 소스 리비전으로 기록하고 해당 체크아웃의 게시 차단을 검증한다. 2026-11-20 모의 서명은 `34dac41`을 사용했고 기존 G6 증거에서 `HASH_MISMATCH`를 확인했다. 현재와 이전 판정은 모두 `authorize_publish=false`다. 정식 게시기, 게시 대상·권한 결정이 남아 있다. [서명과 게이트 증거](../../evidence/RELEASE-READINESS-SIGNING-SMOKE.json) |

기존 G0 승인 범위와 G5 판정은 유효하다. 준비 상태 확인 중 VM 재개, DB 시작, 컨테이너 시작은 각각 0건이었다. 외부 배포와 게시는 **NOT RUN**이다. [호스트 증거](../../evidence/RELEASE-READINESS-HOST.json) · [승인 범위](31-RELEASE-APPROVAL-SCOPE.md) · [제품 G5 기준](32-PRODUCT-G5-ACCEPTANCE.md)

### 현재 환경 판정과 재개 조건

2026-11-24 읽기 전용 점검에서 맥의 메모리 압력은 2단계였다. 재확인 시 1단계였지만 스왑 여유는 약 592 MiB까지 줄었다. Parallels Ubuntu ARM 게스트는 일시 중단 상태로 2 vCPU와 4 GiB가 할당돼 있었고, 맥의 Docker 엔진은 `overlayfs`였다. 네이티브 SQL Server 호스트 점검은 `HOST_LINUX_X86_64`로 차단됐다. DB·VM·컨테이너 기동과 새 성능 실측은 각각 0건이다.

앞선 재판정은 풀 시험의 입력 해시 불일치에서 중단됐다. 이후 메모리 압력 1단계에서 PostgreSQL·MySQL 기능 시험 16건을 순차 실행하고 네 증거 파일을 현재 입력으로 갱신했다. 임시 네이티브 DB와 작업 파일을 모두 정리했으며 VM·컨테이너 기동은 0건이다. 갱신된 네 증거와 기존 Observe 기준선을 대조한 뒤 제품 G5 전체 재판정을 시도했다. Oracle 풀 증거의 입력 해시 불일치에서 중단됐으며, 이전 제품 판정은 해당 리비전의 기록으로 보존한다. [기능 증거 갱신](32-PRODUCT-G5-ACCEPTANCE.md#postgresqlmysql-현재-후보-기능-증거)

`OBSERVE-SHAPE-BYTES-01`의 기능 계약은 통과했다. 2026-11-25 승인된 공식 시험에서 PostgreSQL +45.2410%, MySQL +17.6208%로 양쪽 모두 **FAIL**이며 승인 1회는 소진됐다. Oracle 사전 점검은 두 DB 통과를 기다린다. [기능 증거](../../evidence/PRODUCT-G5-PERFORMANCE-OBSERVE-SHAPE-BYTES-01-CONTRACTS.json) · [공식 성능 증거](../../evidence/PRODUCT-G5-PERFORMANCE-OBSERVE-SHAPE-BYTES-01-RESULT.json)

2026-11-20 맥의 메모리 압력은 경고 단계 2였고 기존 ARM Ubuntu 게스트는 일시 중단 상태였다. 전체 리허설 명령은 Gradle 기동 전에 `HOST_MEMORY_PRESSURE`로 차단됐다. 체크아웃 소스와 승인 범위 확인, 모의 서명, 게시 차단 검증은 통과했다. 준비 점검 중 VM·DB 서버·컨테이너 기동은 0건이었다.

| 작업 | 판정과 재개 조건 |
|---|---|
| 모듈 6종 패키징과 실제 번들 리허설 | **환경 대기, NOT RUN.** macOS 메모리 압력이 정상 수준 1이고 다른 고부하 작업과 겹치지 않을 때, 승인된 후보를 체크아웃하고 `python3 -B tools/release-provider/run-local-release-rehearsal.py`를 실행한다. 실행기는 커밋된 소스의 리비전을 기록한다. 빌드 준비 전과 Gradle 시작 전에 메모리 압력을 확인하며, Gradle 작업자 1명과 전체 600초 한도를 적용한다. [로컬 실행기](../../tools/release-provider/run-local-release-rehearsal.py) |
| Oracle 인스턴스 동시성과 비정상 종료 복구 | **환경 대기, NOT RUN.** 두 Observe p95 프로파일이 통과하고 맥 메모리 압력이 정상화되면 기존 Ubuntu ARM64 게스트의 세션을 보존하며 전용 시험 자원을 확인한다. 게스트에서 `python3 -B tools/release-provider/check-oracle-guest.py`로 가용 메모리, 격리 Docker 엔진과 XFS 프로젝트 쿼터 선행조건을 확인한다. 현재 할당 RAM 4 GiB에는 게스트 OS 여유가 없다. 게스트 점검 통과와 해당 시험 승인 후 보호 실행기를 사용한다. [게스트 점검과 한도](32-PRODUCT-G5-ACCEPTANCE.md#oracle-인스턴스-시험과-로컬-게스트-준비-release-014-release-026) · [Oracle 실행기](../../tools/release-provider/run-oracle-instance.py) |
| 네이티브 SQL Server G5 | **현재 맥과 Parallels에서 실행 불가, NOT RUN.** Parallels는 Apple Silicon에서 Intel 게스트를 에뮬레이션으로 실행한다. Microsoft의 SQL Server Linux 컨테이너 지원 조건은 Intel 또는 AMD x86-64 Linux이며 에뮬레이션은 지원 범위에서 제외된다. 승인된 전용 네이티브 x86-64 Linux 호스트를 확보한 뒤 `python3 -B tools/release-provider/check-sqlserver-host.py`로 네이티브 호스트, 로컬 Docker 용량, 고정 이미지를 확인하고 G5를 예약한다. [Microsoft 플랫폼 요건](https://learn.microsoft.com/en-us/sql/linux/containers/deploy?view=sql-server-ver16) · [Parallels x86 에뮬레이터](https://kb.parallels.com/en/130217) |
| 정식 게시 | **차단, NOT RUN.** G5 합격, 최신 증거에 대한 릴리스 게이트 검증, 운영 서명 준비, 게시 대상·네임스페이스·권한 승인 및 구성을 마치면 재개한다. 로컬 리허설이 성공하면 패키지와 시험 서명 증거를 릴리스 검토에 사용한다. 기록된 게이트 판정은 `authorize_publish=false`다. |
