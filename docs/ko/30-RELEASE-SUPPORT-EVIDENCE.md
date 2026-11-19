# 정식 배포 판단과 지원 근거

[English](../en/30-RELEASE-SUPPORT-EVIDENCE.md) | 한국어

**정식 배포는 BLOCKED다.** 버전 `0.1.0-poc`에서 확인한 범위는 비공개 후보다. G6 결과의 배포 허가 값은 `authorize_publish=false`다. G0는 `NOT GRANTED`, G5는 `NOT RUN`이며 제품 지원은 **NOT CERTIFIED**다. [게이트 결과](../../evidence/PHASE6-GATE.json) · [배포 정책](../../tools/phase6-release-policy.json)

## 제품 책임자가 결정할 G0 항목

1. UDAK 자체 라이선스에 대한 권리자의 결정과 적용할 제품 버전, 포함 모듈, 배포 대상과 채널을 기록한다. 현재 정책은 `project_license=NOT GRANTED`다.
2. 해당 배포물에 포함된 파일과 소비자 빌드가 가져오는 의존성을 SBOM, 라이선스 원문 및 고지문과 대조한다. 각 구성요소를 동봉하는지, 소비자가 내려받는지, 테스트에만 사용하는지 명시한다. 검토한 대상에 책임자의 상업 배포 결정과 해당 계약 참조를 연결한다. 현재 정책은 `commercial_license_approval=NOT GRANTED`다. Boot POM 소비자와 BOM 소비자가 선택하는 버전이 달라 로컬 SBOM은 두 그래프의 합집합인 외부 아티팩트 29개를 기록한다. [후보 그래프 및 패키지](24-STARTERS-CLI-RELEASE-GATES.md)
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

상한에 대한 별도 실행 승인과 제품 성능 합격 기준이 필요하다. 취소와 커밋 전 복구의 이전 기능 검증을 별도로 보존한다. [기존 복구 증거](../../evidence/DB-RECOVERY-VALIDATION.json)

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
