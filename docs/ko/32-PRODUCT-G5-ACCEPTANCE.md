# 제품 G5 인수 기준

[English](../en/32-PRODUCT-G5-ACCEPTANCE.md) | 한국어

PRD는 변환을 끈 Observe 경로의 p95 지연 시간 증가율을 기준 경로 대비 5% 이내로 제한하는 것을 목표로 한다(NFR-02, RELEASE-008). 커넥션 풀 동작은 별도 기능 시험으로 검증한다(RELEASE-009). [PRD](01-PRD.md) · [추적성](16-TRACEABILITY.md)

## Observe 성능 (RELEASE-008)

격리된 소규모 fixture에 고정된 매개변수화 `SELECT` 한 종류를 실행한다. 각 DB 프로파일의 두 경로에서 같은 버전으로 고정한 `JdbcTemplate`, 드라이버, SQL, 바인드 입력, 행 매핑, fixture, 커넥션 구성을 사용한다. 기준 경로는 `JdbcTemplate`을 직접 호출한다. Observe 경로는 SQL 변환을 끈 상태에서 이를 호출한다. 반환 행을 fixture의 기대값 및 두 경로 간에 대조한다.

기준 → Observe와 Observe → 기준의 쌍 순서를 번갈아 실행한다. DB 프로파일별로 각 경로에서 웜업 8건과 측정 96건을 완료한다. 단조 시계로 호출 진입부터 반환까지 잰다. fixture 준비, 시작 간격 대기와 웜업 표본은 p95 계산에서 제외한다. 각 경로에서 측정값 96개를 정렬해 92번째 값을 최근접 순위법으로 구한 p95로 나노초 단위로 기록한다. 프로파일마다 `100 × (Observe p95 − 기준 p95) / 기준 p95`를 계산한다.

두 경로의 호출·측정 표본이 모두 있고 기준 p95가 양수이며, 반올림 전 증가율이 5% 이내이고 실행 오류와 결과 불일치가 각각 0건일 때만 해당 프로파일이 통과한다. 측정값이 누락되면 통과할 수 없다. 프로파일별로 판정하고 이 범위의 통과에는 두 프로파일 모두 통과해야 한다. 소프트웨어 버전, 표본 수, p95, 오류, 불일치, 자원 한도와 정리 결과를 기록한다. 결론은 검증한 쿼리, fixture, 설정과 버전에 한정한다.

| 항목 | 승인한 1회 실행 |
|---|---|
| 프로파일 | 격리된 네이티브 PostgreSQL 17.11 / JDBC 42.7.14 및 MySQL 8.0.46 / Connector/J 26.10.0. 루프백에서 DB를 하나씩 실행한다. |
| SQL 작업 | 웜업을 포함해 DB별 작업 시작은 정확히 208건이다. 동시 진행은 최대 1건, 임의의 연속 1초당 시작은 최대 8건, 시작 간격은 최소 125 ms다. |
| 시간과 자원 | 전체 최대 300초, 개별 프로세스 CPU 시간 최대 90초, DB 프로세스 트리당 PID 최대 48개, RSS 합계 최대 1 GiB, DB별 임시 공간 최대 768 MiB다. 클라이언트 JVM 힙은 256 MiB, 활성 CPU는 2개, 로그는 16 MiB로 제한한다. |
| 중지와 정리 | 작업 전 fixture DB의 상태와 루프백 리스너 소유권을 확인한다. 오류 또는 한도 초과 시 중지하고 정제된 증거를 보존한다. 소유 프로세스 종료와 임시 파일 회수를 검증한다. |

운영자가 앞서 제안한 한도로 실측을 지시했다. 승인된 시험 1회를 2026-11-19에 마쳤다. 두 DB에서 각각 웜업을 포함한 208건을 실행해 반환 행을 검증했고, Observe 이벤트 104건과 오류 0건을 기록했다. 전체 실행 시간은 65.716초였다. 두 네이티브 시험 서버가 종료됐고 임시 파일 자동 정리가 통과했다. [판정 명세](../../tools/product-g5-criteria.json) · [승인 기록](../../evidence/PRODUCT-G5-PERFORMANCE-APPROVAL.json) · [실측 표본](../../evidence/PRODUCT-G5-PERFORMANCE.json)

| DB / 드라이버 | 기준 p95 (ns) | Observe p95 (ns) | 증가율 | NFR-02 |
|---|---:|---:|---:|---|
| PostgreSQL 17.11 / JDBC 42.7.14 | 676,750 | 1,000,333 | 47.8143% | FAIL |
| MySQL 8.0.46 / Connector/J 26.10.0 | 1,719,000 | 2,188,417 | 27.3076% | FAIL |

증거 검증기는 고정된 상한, 표본 수와 실행 순서를 적용한 경로별 96개 표본으로 판정을 재현했다. 이번 값은 고정 SELECT와 시험 커넥션 구성의 지연 시간이며 Observe 내부 단계의 비용을 구분하려면 추가 계측이 필요하다. 승인된 1회 실행을 소진했다. 다음 성능 시험에는 새 한도 승인과 별도 증거 기록이 필요하다. [준비 검증 증거](../../evidence/PRODUCT-G5-PERFORMANCE-PREPARATION.json)

## Observe 실행 경로 후보 (RELEASE-015)

후보는 관측 한 건에서 SHA-256 엔진을 공유하고 해시 도메인을 미리 인코딩한다. 프레임워크와 지문이 같을 때 최근 암묵 쿼리 ID를 재사용한다. 관측기는 파생 항목 한 건을 보관하며 실행을 관측할 때마다 이벤트를 전달한다. 기존 JDBC 프록시에서 자주 호출하는 메서드를 직접 위임한다. 계약 검증에서 고정 해시, 드라이버 위임, 예외 객체의 동일성과 Hibernate·MyBatis·JdbcTemplate 혼용 동작을 확인했다. Core smoke, Observe 215단언, 어댑터 196단언과 H2 10건이 통과했다. [기능 검증 증거](../../evidence/PRODUCT-G5-OBSERVE-CANDIDATE.json)

2026-11-19의 PostgreSQL·MySQL 실측은 원래 소스 버전의 5% 기준에서 실패했다. 새 후보 p95는 **NOT RUN**이다. `python3 -B tools/run-g5-performance.py --proposal OBSERVE-V2`는 승인에 묶일 입력을 출력한다. 승인 후 `--run-id OBSERVE-V2`는 별도 결과 파일과 1회 실행 기록을 사용한다. G5 판정은 과거 실측과 후보 상태를 함께 표시한다. 이전 버전 소스에 묶인 릴리스·호환성 결과는 과거 근거로 유지한다. [기존 판정](../../evidence/PRODUCT-G5-OBSERVE-BASELINE.json) · [후보 시험 준비](../../evidence/PRODUCT-G5-OBSERVE-PREPARATION.json)

## 커넥션 풀 동작 (RELEASE-009)

동일한 격리 DB·드라이버 조합에서 아래 시나리오를 별도의 제한된 기능 시험으로 검증한다. DB가 보고한 물리 세션 식별자를 대조하고 독립 커넥션으로 fixture 데이터에 미친 영향을 확인한다.

| 시나리오 | 인수 기준 |
|---|---|
| 반환과 상태 초기화 | 커밋 전 트랜잭션에서 fixture 행을 변경하고 빌린 커넥션을 닫는다. 롤백을 확인하고 다시 빌린 커넥션의 상태가 구성된 기본값과 일치하는지 검증한다. |
| 물리 커넥션 재사용 | 정상 커넥션을 반환하고 다시 빌릴 때 물리 세션 식별자가 동일한지 확인한다. 새 트랜잭션의 성공을 검증한다. |
| 세션 종료와 교체 | 커밋 전에 소유한 fixture 세션을 종료한다. 독립 커넥션으로 롤백을 확인하고 설정된 타임아웃 안에 풀이 종료된 세션을 교체하는지 확인한다. 교체 세션에서 새 트랜잭션을 커밋해 효과를 검증한다. 중단된 작업의 재실행이 없고 이미 커밋된 fixture 상태가 보존되는지 검증한다. |

두 네이티브 DB에서 HikariCP 6.3.3 기능 시험 4건이 통과했다. 미커밋 상태로 반환하면 쓰기가 롤백되고 연결 상태가 초기화돼 재사용됐다. 종료된 세션은 새 서버 세션으로 교체됐고 후속 커밋을 확인했다. 격리 DB를 종료하고 임시 파일을 회수했다. 취소·타임아웃·커밋 전 세션 유실 결과는 기존 실행 증거를 유지한다. [풀 실행 증거](../../evidence/PRODUCT-G5-POOL.json) · [복구 증거](../../evidence/DB-RECOVERY-VALIDATION.json)

## 서버 재기동 복구 (RELEASE-010)

동일한 네이티브 PostgreSQL·MySQL 프로파일에서 정상 재기동 시험 2건이 통과했다. 각 시험용 DB의 정상 종료를 확인한 뒤 같은 데이터 디렉터리를 소유권이 검증된 새 루프백 포트로 다시 열었다. 커밋 데이터 보존, 롤백 데이터 부재와 독립 커넥션에서의 후속 커밋 조회를 확인했다. 시험 프로세스와 임시 공간은 모두 회수했다. [재기동 실행 증거](../../evidence/PRODUCT-G5-RESTART.json)

## 비정상 종료와 커밋 응답 유실 (RELEASE-011)

PostgreSQL 17.11/JDBC 42.7.14와 MySQL 8.0.46/Connector/J 26.10.0에서 비정상 종료와 커밋 응답 유실을 각각 검증했다. 쓰기 트랜잭션을 열어 둔 채 소유한 서버를 강제 종료했다. 관련 프로세스 종료를 확인한 뒤 같은 데이터 디렉터리를 재기동해 기존 커밋 행 보존, 미커밋 행 부재와 후속 쓰기 커밋을 확인했다. 커밋 응답 시험에서는 단일 연결을 사용하는 로컬 중계가 실제 JDBC 커밋 응답을 폐기했다. 클라이언트가 응답을 기다리는 동안 독립 쿼리로 커밋 행을 확인했다. 클라이언트 연결을 끊자 JDBC 호출이 실패했고 `TransactionGuard`가 자동 재시도를 차단했다. 별도 연결에서 해당 쓰기가 한 번 커밋됐음을 대조했다. 두 네이티브 임시 DB에서 총 4건이 통과했다. [장애복구 증거](../../evidence/PRODUCT-G5-FAILURE.json)

## Oracle ARM64 풀 검증 (RELEASE-012)

네이티브 Linux ARM64 이미지에서 Oracle Free 23.26.4.0.0과 `ojdbc17` 23.26.4.0.0, HikariCP 6.3.3으로 기능 2건이 통과했다. 반환 시 롤백·연결 상태 초기화, 동일한 물리 세션 재사용과 독립 연결에서 후속 커밋 조회를 확인했다. 정지 중인 UDAK 컨테이너 하나를 재사용하고 새 스키마와 고정 크기 테이블스페이스에서 시험했다. 두 시험 자원을 제거하고 기존 컨테이너 12개가 모두 정지 상태임을 확인했다. [Oracle ARM 컨테이너](https://www.oracle.com/database/free/) · [Oracle 실행 증거](../../evidence/PRODUCT-G5-ORACLE.json)

## Oracle 취소와 복구 (RELEASE-013)

같은 Oracle·드라이버 조합에서 5건이 통과했다. 명시적 JDBC 취소와 쿼리 타임아웃 시험은 각각 잠금 대기를 확인한 뒤 중단됐고 ORA-01013을 반환했다. 미커밋 시험 쓰기를 보유한 세션을 종료하자 HikariCP는 다른 물리 세션을 내주었다. 독립 연결로 중단된 쓰기의 롤백과 새 커밋을 확인했다. 단일 연결의 루프백 중계가 실제 커밋 응답을 폐기한 동안 별도 쿼리로 커밋 행을 확인했다. JDBC 호출은 실패했고 `TransactionGuard`는 재시도를 차단했다. `SHUTDOWN IMMEDIATE` 후 동일한 시험 저장 공간으로 재기동해 기존 커밋·롤백 행과 후속 커밋을 검증했다. 임시 스키마·테이블스페이스·파일을 모두 제거했고 기존 컨테이너 12개는 모두 정지 상태로 돌아갔다. [Oracle 복구 증거](../../evidence/PRODUCT-G5-ORACLE-RECOVERY.json)

## 남은 제품 지원 검증

제품 G5는 **BLOCKED**다. PostgreSQL·MySQL의 기존 실측은 Observe p95 상한을 초과했고, 후보 실측은 승인을 기다린다. SQL Server 네이티브 G5에는 격리된 Intel 또는 AMD x86-64 Linux 호스트가 필요하다. 현재 Docker 엔진은 ARM64이고 기존 SQL Server fixture는 에뮬레이션에서 실행했다. Oracle 동시성 파일럿과 인스턴스 비정상 종료 복구는 **NOT RUN**이다. 판정 결과에 프로파일별 미충족 항목을 기록한다. 정식 배포는 **BLOCKED**다. [Microsoft 플랫폼 요구사항](https://learn.microsoft.com/en-us/sql/linux/install-upgrade/setup?view=sql-server-ver16) · [증거 판정](../../evidence/PRODUCT-G5-ACCEPTANCE.json) · [배포 게이트](../../evidence/PHASE6-GATE.json)

## 격리 네이티브 환경 준비 (RELEASE-014)

지정된 시험 호스트에서 `python3 -B tools/release-provider/check-sqlserver-host.py`를 실행한다. 읽기 전용 점검은 Linux x86-64, CPU 공급사, cgroup, 로컬 Docker, 가용 자원과 로컬 고정 이미지를 확인한다. 운영자가 사용 승인과 네이티브 CPU 증빙을 제공한다. 현재 작업 환경의 결과는 `HOST_LINUX_X86_64`이며 네이티브 SQL Server G5는 **NOT RUN**이다. [호스트 점검 증거](../../evidence/PRODUCT-G5-SQLSERVER-HOST-CHECK.json) · [SQL Server 컨테이너 환경 요건](https://learn.microsoft.com/sql/linux/quickstart-install-connect-docker?view=sql-server-ver16)

Oracle 시험 코드를 고정 드라이버로 컴파일했다. `python3 -B tools/release-provider/run-oracle-instance.py --prepare`는 로컬 고정 이미지, 아키텍처, 저장소 상한 선행조건과 정지된 관리 컨테이너 수를 확인한다. `--run`에는 일회용 Oracle 인스턴스 1개에 대한 명시적 승인, 네이티브 ARM64 엔진과 영속 쓰기 계층의 3 GiB 상한이 필요하다. 이 구현은 XFS 프로젝트 쿼터를 적용한 Docker overlay2를 사용하며 기동 전에 Docker의 한도 수락을 확인한다. 로컬 엔진은 overlayfs를 사용해 이 저장소 선행조건을 충족하지 못했다. 기존 컨테이너 12개는 보존했다. [준비 검증 증거](../../evidence/PRODUCT-G5-ORACLE-INSTANCE-PREPARATION.json) · [Docker 저장소 한도](https://docs.docker.com/reference/cli/docker/container/run/#set-storage-driver-options-per-container)

제안한 Oracle 시험은 활성 DB 1개, CPU 2개, RAM 3 GiB, PID 512개, 작업 시간 600초로 제한한다. 동시 트랜잭션 최대 2개에서 정확히 48건을 시작하며, 연속 1초당 시작은 최대 4건이다. 새로 만든 시험 인스턴스만 한 차례 강제 종료한다. 재기동 후 동일 DB, 새 기동 시각, 커밋 행 보존, 미커밋 쓰기 롤백과 후속 커밋을 확인한다. Oracle 신규 실행 증거는 대기 상태다.
