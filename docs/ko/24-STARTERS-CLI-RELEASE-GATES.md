# Phase 6 Starter·CLI·배포 게이트

[English](../en/24-STARTERS-CLI-RELEASE-GATES.md) | 한국어

Phase 6은 FR-017, T-018, T-019, T-020 및 T-021의 읽기 전용 CLI를 다룬다. MCP는 후속 작업이다. 로컬 CI와 G6 비공개 후보 게이트는 PASS이며, 정식 배포는 BLOCKED다. [추적성](16-TRACEABILITY.md)

## Spring Boot Starter 분리

| 로컬 후보 좌표 | 대상 런타임 |
|---|---|
| `dev.udak:starter-boot3:0.1.0-poc` | Spring Boot 3.5.16 / Spring Framework 6.2.19 |
| `dev.udak:starter-boot4:0.1.0-poc` | Spring Boot 4.1.2 / Spring Framework 7.0.10 |

애플리케이션의 Boot 메이저 버전에 맞는 Starter를 사용한다. Boot가 `AutoConfiguration.imports`로 자동 발견한다. 시작 검사는 두 Starter가 함께 있거나 Boot 메이저가 다르면 `udak.enabled=false`에서도 시작을 거부한다. 기본 Observe 구성은 `SqlObserver`와 아무 동작도 하지 않는 `ObservationSink`를 제공한다. 애플리케이션에서 observer 또는 sink 빈을 직접 제공할 수 있다. Hibernate, MyBatis, JDBC의 관측 지점은 명시적으로 연결한다. Rewrite는 `DENY`이며 활성화 설정은 시작 시 거부한다. [설정 키](11-API-CONFIG-SCHEMA.md)

지연 초기화되는 `SpringJdbcExecutor`를 자동 구성하려면 `udak.jdbc.enabled=true`, 명시적 `DbVendor`, 단일 `DataSource` 빈이 필요하다. 애플리케이션에서 `SqlExecutor`를 직접 제공할 수 있다. DataSource가 여러 개면 `@Primary`를 지정해도 실행기를 자동 구성하지 않는다. 실행기는 해당 DataSource의 Spring 트랜잭션에 참여한다.

## 보호된 로컬 검증

```bash
python3 tools/local-ci.py
# Individual steps:
python3 tools/run-phase6.py
python3 tools/test-phase6-verifier.py
python3 tools/verify-phase6.py
python3 tools/udak-cli.py inspect --format json
python3 tools/release-gate.py
```

보호 하네스는 JDK 17 이상, Python 3, Gradle 8.14.3을 사용하며 고정 Gradle 배포본과 Maven Central에서 다운로드한다. `starter-testkit/`의 독립 Gradle 빌드가 두 Starter와 필요한 UDAK 모듈을 패키징한다. 소비 앱은 Maven POM을 통해 후보 JAR을 해석한다. 각 라인에서 외부 트랜잭션의 실제 H2 롤백을 포함한 일반 앱 시나리오 11개를 검사한다. 별도 매트릭스에서 Starter 혼합 1개와 잘못된 Boot 메이저 조합 2개의 거부를 검사한다. 로컬 CI에는 `tools/local-ci.py`를 사용한다. GitHub Actions는 금지한다.

하네스 총 실행 시간의 상한은 1,800초다. Gradle 힙 512 MiB, 메타스페이스 256 MiB, 활성 CPU 2개, worker 1개로 제한한다. 소비 앱 JVM 힙 상한은 256 MiB다. 작업공간은 2 GiB/20,000개 파일, 후보는 200 MiB/500개 파일로 제한한다. Phase 6은 내장 H2를 쓰며 새 컨테이너 0개, 기존 정지 DB 컨테이너 12개 보존이 실행 범위다.

검증기는 기존 후보와 증거를 검사한다. 읽기 전용 CLI는 지정된 로컬 검증 증거를 읽고 해시를 확인한다. 애플리케이션 설정, SQL, DB, 네트워크에는 접근하지 않는다.

## 후보와 정식 배포

로컬 패키징은 비공개 평가 후보를 생성한다. G6 로컬 검토 범위는 패키지 메타데이터, checksum, SBOM, NOTICE, 버전/API 호환성 증거다. 정식 배포는 종료 코드 `2`와 `BLOCKED` 상태를 반환한다. UDAK 자체 라이선스와 G0 상용 라이선스 판단 승인, G5 동시성·성능·취소·복구 증거, 승인되고 구현된 게시 경로가 필요하다. 외부 게시와 제품 지원 인증은 NOT RUN이다. [검증 게이트](08-TEST-VALIDATION.md)

공식 참고 자료. [Boot 3.5 요구 사항](https://docs.spring.io/spring-boot/3.5/system-requirements.html), [Boot 4.1 요구 사항](https://docs.spring.io/spring-boot/4.1/system-requirements.html), [Spring Boot 자동 구성](https://docs.spring.io/spring-boot/reference/features/developing-auto-configuration.html), [Maven Central 게시 요구 사항](https://central.sonatype.org/publish/requirements/).

검증 앱은 Boot의 기본 DataSource·트랜잭션 매니저·JdbcTemplate 자동 설정과 SQL 초기화를 제외하여 UDAK의 동작을 검사한다. 서비스 앱에서는 Boot 자체 구성이나 사용자 빈이 DataSource를 초기화할 수 있다. Java 17은 컴파일 대상이며 실제 실행 JDK는 검증 증거에 기록한다.

의존성은 Gradle 프로젝트와 POM 단독 소비자의 실제 그래프를 각각 고정한다. Boot 4 POM 소비자는 Commons Logging 1.3.5와 Micrometer 1.16.8을, Boot BOM 소비자는 1.3.6과 1.17.2를 선택한다. 두 경로 모두 동일한 Boot 4.1.2 / Spring 7.0.10을 사용한다. 추가 BOM 소비 앱까지 실제 검사하며, 고정된 외부 artifact 합집합 29개를 SBOM에 기록한다.

## 실제 검증 결과

| 검사 | 결과 |
|---|---|
| Boot 3 POM / Boot 4 POM / Boot 4 BOM | 각 11개 시나리오·79개 단언 PASS |
| 두 Starter 혼합 / 잘못된 메이저 2개 | 각 3개 단언, 시작 거부 PASS |
| CLI 계약 / 검증기 변조·보호 계약 | 41개 / 50개 PASS, skip 0 |
| 패키지 재현성 / 배포 증거 | JAR·POM·module·sources·Javadoc 30개 동일, SBOM 등 포함 35개 |
| 기존 공개 API / Core 회귀 | 기존 소스 22개 유지, Core smoke PASS |
| 성공 실행 자동 정리 | 빌드 2,351개 파일 / 375,381,725바이트, 잔여 0 |
| 실패·시간 초과·중단 합성 검사 | 각 소유 output 1개·0바이트 회수, 잔여 0 |

실제 실행은 JDK 21.0.13 / Gradle 8.14.3이며 Java 17 대상 class를 생성했다. 하네스가 허용하는 JDK 범위는 17–24다. [실행 원본](../../evidence/PHASE6-VALIDATION.json), [검증기 50개](../../evidence/PHASE6-VERIFIER-VALIDATION.json), [로컬 CI](../../evidence/PHASE6-LOCAL-CI.json), [G6 후보 게이트](../../evidence/PHASE6-GATE.json).

후보 JAR/POM과 전용 캐시는 검사 후 자동 정리하므로 CLI는 `candidate_artifacts=NOT AVAILABLE`로 표시한다. 이는 보존된 실행 증거의 검증 상태와 구분한다. `tools/local-ci.py`로 동일 입력의 후보를 다시 생성·검증할 수 있다. 실패한 실행의 정제된 보고서는 `.git/` 안에 보존하며, 불명 자료는 자동 삭제하지 않는다. 기존 정지 DB 12개는 유지했다.

## 차기 작업

제품 합격 기준을 확정하고 남은 G5와 DB 지원 시나리오를 검증한다. 확장 단계에서는 실제 JDK 17의 전체 레거시 데모, 일회용 로컬 OpenPGP 서명 및 승인된 G5 1차 시험을 확인했다. 게시 좌표·권한, 운영용 서명·게시와 전체 DB 지원 인증은 남아 있다. MCP는 별도 후속 범위다. [확장 단계 결과](30-RELEASE-SUPPORT-EVIDENCE.md) · [G0·G5 승인 범위](31-RELEASE-APPROVAL-SCOPE.md)
