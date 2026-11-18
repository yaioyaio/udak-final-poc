# 관리형 실DB G2 결과

[English](../en/20-MANAGED-G2-RESULTS.md) | 한국어

## 최소 기능 판정

**G2 PASS.** 전용 실DB 4종에서 최소 CRUD/Query와 Spring JDBC 로컬 트랜잭션 검사 40개를 통과했다. 각 프로파일에서 INSERT_NULL, READ_NULL, UPDATE, INSERT_SECOND, INSERT_THIRD, PAGE, BIND, COMMIT, ROLLBACK, DELETE를 실행하고 fixture 정리와 서버 정지를 확인했다. [G2-REAL-VALIDATION.json](../../evidence/G2-REAL-VALIDATION.json)

| 프로파일 | 실서버 버전 | 고정 JDBC 드라이버 | 플랫폼 | 결과 |
|---|---|---|---|---|
| POSTGRESQL | 17.12 | postgresql 42.7.14 | linux/arm64 | 10 PASS |
| MYSQL | 8.4 | mysql-connector-j 26.10.0 | linux/arm64 | 10 PASS |
| SQLSERVER | 16.0 (2022) | mssql-jdbc 13.6.2.jre11 (metadata 13.6.2.0) | linux/amd64 | 10 PASS |
| ORACLE | 23.26 Free | ojdbc17 23.26.4.0.0 | linux/arm64 | 10 PASS |

인접한 동일 호스트 회귀 보고서에서 확인한 JDK는 21.0.13이며 G2 JVM 버전은 별도 probe하지 않았다. 컴파일 대상은 `--release 17`, Spring JDBC/Tx는 6.2.19다. 서버 이미지는 플랫폼별 digest로 고정했다. SQL Server 1종과 나머지 3종을 동일 소스의 두 배치로 실행했다. 각 배치의 전체 게이트가 INCOMPLETE로 표시되는 것은 일부 프로파일만 실행했기 때문이다. 4종 전체 판정은 합본 증거의 PASS를 따른다. [서버 이미지 매니페스트](../../tools/g2-server-images.json) · [SQL Server 배치](../../evidence/G2-RUN-SQLSERVER.json) · [나머지 DB 배치](../../evidence/G2-RUN-OTHER-DATABASES.json)

## 실행과 보존

- Python 하네스와 Java JDBC runner가 새 DB 4개를 순차 실행했다. 동시 활성 인스턴스는 최대 1개, 컨테이너당 상한은 CPU 2개, 메모리 4 GiB, PID 512개였다. 포트는 루프백에만 게시했고 자동 재시작은 비활성화했다. 기존 Docker 컨테이너 64개와 Parallels VM은 변경하지 않았으며 VM을 재개하지 않았다.
- 실행 전에 여유 디스크 40 GiB 이상과 추가 메모리 여유 1 GiB를 확인한다. 이미지 pull의 2 GiB 제한은 Docker Engine이 보고하는 진행량 기준이다. 전체 디스크 사용량의 상한은 별도다. `compressed_layer_bytes`가 0인 항목은 OCI 상세 메타데이터에서 압축 레이어 크기를 확인할 수 없었다는 뜻이다.
- 하네스는 새 자격증명을 메모리에서 생성하고 Docker Engine Unix 소켓의 HTTP 요청과 Java 전용 stdin으로 전달한다. `DedicatedRuntimeProvider`는 이 입력으로 전용 `DataSource`를 구성한다. dotenv, 명령 인수, 로그, 증거 및 모델 입력에 값을 넣지 않았다. Docker 데몬은 정지한 컨테이너의 환경 설정에 값을 보존할 수 있으며 `Config.Env`와 원본 애플리케이션 로그는 열람하지 않았다.
- fixture 4개의 DROP과 컨테이너 4개의 종료를 확인했다. 전용 DB 데이터, 컨테이너 쓰기 레이어, 익명 볼륨 2개(PostgreSQL·MySQL)를 보존했다. 전체 데이터 크기는 미측정이며 관리형 컨테이너 보존 상한은 8개다. PostgreSQL과 MySQL은 exit 0, SQL Server는 30초 제한을 지정한 Docker stop 요청 뒤 exit 137, Oracle은 exit 143이었다. 4개 모두 OOMKilled=false였고 기존 64개 컨테이너는 계속 실행 중이었다. [컨테이너 보존 증거](../../evidence/G2-CONTAINER-RETENTION.json)
- 공통 실행기의 자동 정리는 재생성 가능한 작업 파일 107개(45,380,214바이트)를 회수했다. 실행 의도 및 감사 저널은 `.git/`에 보존했고 기존 용도 미확정 감사 자료는 정리 대상에서 제외했다. 공통 실행기에 연결된 경로에서 자동 정리를 검증했다.

## 회귀와 미검증 범위

| 검증 | 결과 |
|---|---|
| Phase 2 회귀 | PASS · Core smoke, 기본 SPI 74개, 외부 SPI 83개, CRUD API 313개, Spring JDBC/H2, DB 기반 71개, 전용 provider 계약 128개 |
| 관리형 안전장치 | 7개 PASS · 생성 제한과 비공개 결과, 소유권, DB 컨테이너 삭제 차단, 종료된 probe의 볼륨 보존, 루프백, 원자적 교체 실패 시 보존, 비공개 파이프 |
| 실DB 증거 검증기 | 6개 PASS · 완전한 증거 승인, 프로파일 누락·시간 초과·정리 미확정·소스 불일치·DB 식별자 중복 거부 |
| SQL Server 네이티브와 벤더 플랫폼 인증 | NOT RUN · ARM64 호스트의 로컬 Docker x86 에뮬레이션에서 실제 SQL Server 기능을 실행했으며 벤더 인증은 NOT GRANTED |
| SQL Server 정상 종료와 재시작 후 복구 | NOT RUN |
| Gradle, Spring Boot/JPA/MyBatis 앱과 성능 검증 | NOT RUN |
| 제품 재배포 | NOT GRANTED |

Phase 2 회귀의 실DB 행은 NOT RUN이다. 실DB 실행과 판정은 별도 G2 증거에 기록했다. [Phase 2 회귀](../../evidence/PHASE2-VALIDATION.json) · [관리형 안전장치](../../evidence/G2-MANAGED-SAFETY.json) · [증거 검증기](../../evidence/G2-EVIDENCE-VERIFIER-VALIDATION.json) · [드라이버와 실행 정책](19-REAL-DB-G2.md)

## 재현

| 작업 | 명령 |
|---|---|
| 보존된 증거와 작업 트리 일치 검증 | `python3 tools/verify-real-g2.py` |
| Phase 2 계약 회귀 | `python3 tools/run-phase2.py` |
| 새 전용 실DB 실행 | `python3 tools/run-managed-g2.py` |

실DB 재현은 새 컨테이너 4개를 순차 기동하고 정지한 컨테이너와 데이터를 보존한다. 기존 증거 확인은 증거 검증기만 실행한다.

## 다음 단계

Phase 3의 FR-005~007에서 JPA/MyBatis/JdbcTemplate Observe 어댑터와 민감값을 제외한 fingerprint 이벤트 계약을 검증한다. 동일 DataSource에서 flush, cache, rollback 호환성을 확인한다. Rewrite는 기본 차단하고 Core는 Spring에 의존하지 않는다. [요구 추적](16-TRACEABILITY.md)
