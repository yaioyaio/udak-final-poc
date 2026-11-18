# UDAK Final Architecture + Runnable POC (v0.1.0-poc)

[English](README.md) | 한국어

**UDAK: Unified Data Access & Compatibility Kit** — Spring Boot 기존 JPA / MyBatis / JdbcTemplate 유지보수와 신규 통합 데이터 접근 API를 위한 **설계 및 검증 패키지**.

> ⚠️ 이 ZIP은 제품 최종 릴리스가 아닌 **최종 목표 아키텍처와 1차 실행 POC**이다. SQL 컴파일러는 제한된 구문만 처리하고, 승인된 SELECT의 명시적 JDBC 선택 변환은 H2와 4종 실DB의 고정 fixture에서 G4를 통과했다. 선택한 4종 실DB 이미지에서 최소 CRUD·트랜잭션 G2는 통과했으며, 제품 지원 인증과 별도 범위다. 테스트 증거를 확인한 후 단계적으로 확장한다.

## 1. 바로 실행

JDK 17 이상만 필요 (외부 의존성 없음):

```bash
./tools/run-core-smoke.sh
```

이 테스트는 `javac`로 직접 컴파일하여 SQL 렌더링, 바인딩 순서, 허용된 식별자, 승인 기반 SQL 변환 게이트, 복수 DataSource 경고를 검사한다.

Spring Boot 혼합 접근 샘플 (Gradle + Maven Central 접근 필요):

```bash
./tools/run-spring-demo.sh
# 또는
# gradle :spring-boot-demo:test
# gradle :spring-boot-demo:bootRun
```

Demo는 H2 단일 DataSource에서 JPA + MyBatis + JdbcTemplate의 동일 트랜잭션 참여와 flush 필요성을 보여준다. H2 MODE=PostgreSQL은 **PostgreSQL 자체의 호환성 증명이 아니다**.

Phase 1 외부 파서 계약·고정 의존성/라이선스 검사(Python 3, JDK 17+, Maven Central 접근 필요):

```bash
python3 tools/run-phase1.py
```

제한 하네스는 실패 증거를 보존하고 자신이 만든 임시 작업 폴더만 정리한다. [엔진 비교](docs/ko/17-SQL-ENGINE-EVALUATION.md)와 [실행 결과](docs/ko/14-POC-RESULTS.md)를 참조한다.

Phase 2 최소 API·Spring JDBC/H2·4 DBMS 검증 기반:

```bash
python3 tools/run-phase2.py
```

[CRUD/JDBC 검증](docs/ko/18-CRUD-JDBC-VALIDATION.md)과 [실제 4종 G2 결과](docs/ko/20-MANAGED-G2-RESULTS.md)를 따른다. 전용 provider를 직접 구현해 4종 실DB의 40개 최소 계약과 fixture 정리를 검증했다. SQL Server x86 에뮬레이션은 기능 검증이며 네이티브 플랫폼 인증은 NOT RUN이다.


실제 4종 G2의 기존 증거만 검증(새 서버 기동 없음):

```bash
python3 tools/verify-real-g2.py
```

전용 환경을 새로 준비해 재실행하려면 `python3 tools/run-managed-g2.py`를 사용한다. 한 번에 DB 한 개를 기동하고 완료 후 정지·보존하므로 [자원·보존 조건](docs/ko/20-MANAGED-G2-RESULTS.md)을 먼저 확인한다.

Phase 3 Observe 계약과 실제 Hibernate/MyBatis/JdbcTemplate 동일 DataSource 호환성 검사:

```bash
python3 tools/run-phase3.py
# 기존 H2·실DB 증거만 확인(서버 기동 없음)
python3 tools/verify-phase3.py
```

Observe Core 202개·어댑터 188개, H2 10개·실DB 4종 40개 항목 PASS. [검증 결과·명시적 연결 방법·관측 제외 범위](docs/ko/21-LEGACY-OBSERVE-RESULTS.md)를 따른다. `python3 tools/run-phase3-real.py`는 새 전용 DB를 생성하므로 현재 보존된 12개와 자원 상한을 먼저 확인한다.

Phase 4 명시적 트랜잭션 진단과 실제 Spring/H2 계약 검사

```bash
python3 tools/run-phase4.py
python3 tools/verify-phase4.py
```

명시적 구성·현재 스레드 정책과 Spring/H2 검증 PASS. 새 4종 실DB 트랜잭션 매트릭스와 Boot/Gradle 검증은 NOT RUN이다. [상세 결과](docs/ko/22-TRANSACTION-GUARD-RESULTS.md).

Phase 5 승인 기반 선택 변환 검증

```bash
python3 tools/run-phase5.py
# DB 기동 없이 보존된 G4 증거만 확인
python3 tools/verify-phase5.py
```

로컬 계약·H2 동등성과 4종 실DB 32개 검증 범주가 통과했다. 전체 증거 검사 20개와 G4는 PASS다. [상세 결과](docs/ko/23-SELECTIVE-REWRITE-RESULTS.md).

Phase 6 별도 Boot Starter·로컬 검증·배포 게이트

```bash
python3 tools/local-ci.py
python3 tools/udak-cli.py inspect --format json
python3 tools/release-gate.py
```

Phase 6 로컬 CI와 G6 비공개 후보 게이트는 PASS다(Boot 구성 3개, CLI 검사 41개, 검증기 검사 50개). 정식 배포 게이트는 BLOCKED 상태로 종료 코드 2를 반환한다. [Starter 설정·보호 실행·배포 조건](docs/ko/24-STARTERS-CLI-RELEASE-GATES.md)

확장 Phase 1은 기존 Observe 어댑터에 SQL 인벤토리와 로컬 base/head PR 보고서를 추가한다.

```bash
python3 tools/run-sql-inventory.py
```

[수집·비교·검증 방법](docs/ko/25-SQL-INVENTORY-PR-REPORT.md)

확장 Phase 2는 Spring Framework 6.2.19 Observe 훅에 명시적 로컬 트랜잭션 추적을 추가한다. Spring/H2 추적 시나리오 8개와 단언 318개가 통과했다.

```bash
python3 tools/run-tx-trace.py
```

[추적 연결과 이벤트 해석](docs/ko/26-TRANSACTION-BOUNDARY-TRACE.md)

확장 Phase 3은 정규화된 스키마 영향 분석과 PostgreSQL·MySQL의 실제 쿼리 회귀 4개 조합을 통과했다.

```bash
python3 tools/run-schema-regression.py
```

[영향 분석 CLI 입력과 fixture 범위](docs/ko/27-SCHEMA-IMPACT-REGRESSION.md)

확장 Phase 4는 PostgreSQL과 MySQL에서 제한된 범위의 JDBC 취소, 타임아웃, 세션 복구를 다룬다. [Fixture 범위와 검증 상태](docs/ko/28-DB-CANCELLATION-RECOVERY.md)

확장 Phase 5는 명시적으로 승인된 JDBC SELECT 변환에 로컬 승인·폐기 이력을 추가한다. [사용 방법과 검증 상태](docs/ko/29-QUERY-APPROVAL-HISTORY.md)

## 2. 핵심 제품 정책

- **Primary customer:** 여러 DBMS/프레임워크를 운영하는 Spring Boot SI/SM/기업 백엔드 팀
- **New:** 안정화 이후 Simple CRUD + Fluent Query API (현재 core는 제한된 컴파일러 SPI 데모)
- **Legacy:** 기존 소스 변경 최소화, Observe → Analyze → Approved Rewrite 순서
- **SQL engine:** 교체 가능한 `SqlCompiler`/translation SPI. 외부 엔진 채택은 라이선스·기능 검증 후
- **Transactions:** Spring이 관리하고, UDAK는 설정·위험을 감지한다. 다중 DB 원자성 보장은 하지 않는다
- **Supported target DBMS:** PostgreSQL, MySQL, SQL Server, Oracle (고정 이미지의 최소 기능 G2 PASS; 광범위 지원 인증은 별도)

## 3. 문서 길잡이

| 문서 | 내용 | English |
|---|---|---|
| [00-EXECUTIVE-DECISIONS.md](docs/ko/00-EXECUTIVE-DECISIONS.md) | 최종 목표와 기존 기술 대비 차별점 | [English](docs/en/00-EXECUTIVE-DECISIONS.md) |
| [01-PRD.md](docs/ko/01-PRD.md) | 요구사항, 사용자, KPI, 범위 | [English](docs/en/01-PRD.md) |
| [02-ARCHITECTURE.md](docs/ko/02-ARCHITECTURE.md) | 논리·배포 구조, 의존성, ADR | [English](docs/en/02-ARCHITECTURE.md) |
| [03-API-SPEC.md](docs/ko/03-API-SPEC.md) | New API, Compiler/Executor/Guard 계약 | [English](docs/en/03-API-SPEC.md) |
| [04-DBMS-COMPATIBILITY.md](docs/ko/04-DBMS-COMPATIBILITY.md) | 네 DBMS 전략, SQL 의미 차이 | [English](docs/en/04-DBMS-COMPATIBILITY.md) |
| [05-LEGACY-COMPATIBILITY.md](docs/ko/05-LEGACY-COMPATIBILITY.md) | JPA/MyBatis/JDBC 적용과 승인 변환 | [English](docs/en/05-LEGACY-COMPATIBILITY.md) |
| [06-TRANSACTION-CONSISTENCY.md](docs/ko/06-TRANSACTION-CONSISTENCY.md) | 로컬/다중DB 트랜잭션 및 시간 정책 | [English](docs/en/06-TRANSACTION-CONSISTENCY.md) |
| [07-SECURITY-OBSERVABILITY.md](docs/ko/07-SECURITY-OBSERVABILITY.md) | 보안·로깅·운영 지표 | [English](docs/en/07-SECURITY-OBSERVABILITY.md) |
| [08-TEST-VALIDATION.md](docs/ko/08-TEST-VALIDATION.md) | 테스트 매트릭스·증거·품질 게이트 | [English](docs/en/08-TEST-VALIDATION.md) |
| [09-WBS-ROADMAP.md](docs/ko/09-WBS-ROADMAP.md) | Phase, 선행관계, 작업 항목 | [English](docs/en/09-WBS-ROADMAP.md) |
| [10-USECASES-EVENTSTORMING.md](docs/ko/10-USECASES-EVENTSTORMING.md) | UseCase / EventStorming | [English](docs/en/10-USECASES-EVENTSTORMING.md) |
| [11-API-CONFIG-SCHEMA.md](docs/ko/11-API-CONFIG-SCHEMA.md) | Spring 설정 계약 및 구성 예시 | [English](docs/en/11-API-CONFIG-SCHEMA.md) |
| [12-MIGRATION-RUNBOOK.md](docs/ko/12-MIGRATION-RUNBOOK.md) | 기존 프로젝트 도입·롤백 절차 | [English](docs/en/12-MIGRATION-RUNBOOK.md) |
| [13-AGENT-DEVELOPMENT-GUIDE.md](docs/ko/13-AGENT-DEVELOPMENT-GUIDE.md) | Codex / Claude Code 공통 지침 | [English](docs/en/13-AGENT-DEVELOPMENT-GUIDE.md) |
| [14-POC-RESULTS.md](docs/ko/14-POC-RESULTS.md) | 실제 검증 사실과 미검증 항목 | [English](docs/en/14-POC-RESULTS.md) |
| [15-MARKET-VS-EXISTING.md](docs/ko/15-MARKET-VS-EXISTING.md) | 기존 라이브러리 비교·제품화 판단 | [English](docs/en/15-MARKET-VS-EXISTING.md) |
| [16-TRACEABILITY.md](docs/ko/16-TRACEABILITY.md) | 요구↔코드↔테스트 매핑 | [English](docs/en/16-TRACEABILITY.md) |
| [17-SQL-ENGINE-EVALUATION.md](docs/ko/17-SQL-ENGINE-EVALUATION.md) | Phase 1 엔진·라이선스 선택과 한계 | [English](docs/en/17-SQL-ENGINE-EVALUATION.md) |
| [18-CRUD-JDBC-VALIDATION.md](docs/ko/18-CRUD-JDBC-VALIDATION.md) | 최소 API·Spring JDBC·4 DBMS 검증 기반과 G2 경계 | [English](docs/en/18-CRUD-JDBC-VALIDATION.md) |
| [19-REAL-DB-G2.md](docs/ko/19-REAL-DB-G2.md) | JDBC 드라이버·라이선스 고정, 전용 연결과 실행 정책 | [English](docs/en/19-REAL-DB-G2.md) |
| [20-MANAGED-G2-RESULTS.md](docs/ko/20-MANAGED-G2-RESULTS.md) | 실제 4종 G2 결과·자원·보존·차기 작업 | [English](docs/en/20-MANAGED-G2-RESULTS.md) |
| [21-LEGACY-OBSERVE-RESULTS.md](docs/ko/21-LEGACY-OBSERVE-RESULTS.md) | Observe 어댑터·flush/cache/rollback 호환성 결과 | [English](docs/en/21-LEGACY-OBSERVE-RESULTS.md) |
| [22-TRANSACTION-GUARD-RESULTS.md](docs/ko/22-TRANSACTION-GUARD-RESULTS.md) | 명시적 트랜잭션 진단·차단 정책과 Spring/H2 검증 | [English](docs/en/22-TRANSACTION-GUARD-RESULTS.md) |
| [23-SELECTIVE-REWRITE-RESULTS.md](docs/ko/23-SELECTIVE-REWRITE-RESULTS.md) | 승인 SQL 선택 변환·실제 4종 G4 결과 | [English](docs/en/23-SELECTIVE-REWRITE-RESULTS.md) |
| [24-STARTERS-CLI-RELEASE-GATES.md](docs/ko/24-STARTERS-CLI-RELEASE-GATES.md) | Spring Boot Starter 분리, 읽기 전용 CLI, 배포 게이트 | [English](docs/en/24-STARTERS-CLI-RELEASE-GATES.md) |
| [25-SQL-INVENTORY-PR-REPORT.md](docs/ko/25-SQL-INVENTORY-PR-REPORT.md) | SQL 인벤토리와 base/head PR 보고서 | [English](docs/en/25-SQL-INVENTORY-PR-REPORT.md) |
| [26-TRANSACTION-BOUNDARY-TRACE.md](docs/ko/26-TRANSACTION-BOUNDARY-TRACE.md) | 명시적 Spring 트랜잭션 경계 추적과 SQL 관측 연결 | [English](docs/en/26-TRANSACTION-BOUNDARY-TRACE.md) |
| [27-SCHEMA-IMPACT-REGRESSION.md](docs/ko/27-SCHEMA-IMPACT-REGRESSION.md) | 정규화된 스키마 영향 분석과 쿼리별 실DB 회귀 | [English](docs/en/27-SCHEMA-IMPACT-REGRESSION.md) |
| [28-DB-CANCELLATION-RECOVERY.md](docs/ko/28-DB-CANCELLATION-RECOVERY.md) | JDBC 취소, 타임아웃, 세션 복구 | [English](docs/en/28-DB-CANCELLATION-RECOVERY.md) |
| [29-QUERY-APPROVAL-HISTORY.md](docs/ko/29-QUERY-APPROVAL-HISTORY.md) | 영속적인 쿼리 승인·폐기 이력 | [English](docs/en/29-QUERY-APPROVAL-HISTORY.md) |

문서는 같은 파일명을 사용해 `docs/en/`과 `docs/ko/`에서 한 쌍으로 관리한다. 내용 변경 시 두 언어를 함께 갱신하고 요구 ID·명령·버전·검증 상태를 동일하게 유지한다. 메인 `README.md`는 영문이며 한국어는 `README-KO.md`에 둔다.

## 4. 프로젝트 모듈

- `core/`: 순수 Java, 외부 의존성 없는 SPI + 제한된 SQL Dialect + 정책 검사 **실행 가능**
- `spring-boot-demo/`: Spring Boot 3.5.16 + JPA + MyBatis + JDBC + H2 예제 **Phase 3에서 업무 소스를 프로그램 방식으로 검증, 전체 Boot/Gradle 실행 NOT RUN**
- `sql-jsqlparser/`: Core 밖의 고정 JSqlParser 5.4 검증 어댑터 — **파서/SPI 계약 통과, SQL 변환·실DB 지원 주장은 제외**
- `udak-api/`: 테이블별 allowlist를 적용하는 최소 CRUD/Query 계약
- `jdbc-spring/`: 외부 DataSource의 Spring 트랜잭션에 참여하는 실행기
- `db-testkit/`: 직접 관리하는 4종 provider·전용 fixture; 실제 최소 기능 G2 PASS
- `observe-core/`: JDK 전용 비민감 Observe 이벤트·형태 해시 계약.
- `legacy-observe/`: Hibernate/MyBatis/JDBC 명시적 Observe 어댑터.
- `sql-inventory/`: Observe용 JDK 전용 제한 수집과 스냅샷 내보내기.
- `tx-trace-spring/`: Spring 로컬 트랜잭션 경계와 SQL 관측의 명시적 연결.
- `tx-trace-spring/`: 기존 Observe 훅에 선택적으로 연결하는 Spring 트랜잭션 추적.
- `legacy-compat-testkit/`: 기존 Entity/Repository/Mapper/service를 사용하는 동일 DS 호환성 검사.
- `consistency-core/`: JDK 전용 트랜잭션 진단·차단 정책과 불변 보고서.
- `consistency-spring/`: 명시적 Spring 구성·현재 스레드 진단.
- `consistency-testkit/`: 실제 Spring/H2 트랜잭션 진단 계약.
- `rewrite-core/` — JDK 전용 승인·증거 레지스트리와 변환 SPI.
- `rewrite-jsqlparser/` — JSqlParser 5.4 제한 SELECT paging 변환.
- `rewrite-jdbc/` — 승인된 변환의 명시적 Spring JDBC 실행.
- `rewrite-testkit/` — 선택 변환 동등성·트랜잭션 검증.
- `starter-boot3/`와 `starter-boot4/` — Boot별 자동 구성과 Observe 기본값.
- `starter-testkit/` — 독립 Gradle 패키징과 별도 소비 앱 계약.
- `tools/`: 실행 스크립트
- `evidence/`: 실제 통과한 테스트 출력
- `docs/en/`: 영문 문서
- `docs/ko/`: 한국어 문서

## 5. 환경과 버전

- Java 17+ (JDK 21에서도 코어를 `--release 17`로 빌드)
- Phase 6 Starter 대상은 Spring Boot 3.5.16 / Spring Framework 6.2.19와 Spring Boot 4.1.2 / Spring Framework 7.0.10이다.
- MyBatis Starter 3.0.5 (Boot 3 라인, 버전 좌표는 실제 Gradle 의존성 해석 때 확인 필요)
- Phase 6 하네스는 데모 Wrapper와 별도로 Gradle 8.14.3을 고정한다.
- Gradle 8.14+ 권장. Gradle Wrapper 스크립트·설정·jar를 포함한다. Gradle 데모 의존성 해석과 전체 Boot 실행은 미검증이며, Phase 3은 공개 Maven 의존성을 별도로 해석해 검증했다

공식 참고: https://docs.spring.io/spring-boot/ , https://mybatis.org/spring-boot-starter/mybatis-spring-boot-autoconfigure/index.html

## 6. 절대 보장하지 않는 사항

- SQL 한 번 작성으로 모든 DBMS 전용 기능이 100% 동일해짐
- JPA 1차 캐시/Flush 자동 동기화
- 여러 DB에 대한 단일 `@Transactional`의 원자적 Commit
- 스키마·타임존·격리 수준·실행계획 동일성
- 검증되지 않은 SQL의 자동 안전 변환

이 부분은 기능 경계와 보증 계약을 명시하여 운영 사고를 예방한다.

## 7. 보안 파일 제외

`.gitignore`와 `.dockerignore`는 인증정보·개인키·클라우드/인프라 상태·DB 덤프·네트워크 캡처·원본 보안 스캔 결과를 제외한다. 원본 스캔 결과는 `.security-local/`에 보관하고 정제한 보안 문서와 검증 증거만 공유한다. 이미 추적된 파일과 `git add -f`는 별도로 인덱스를 점검해야 한다. 이 제외 설정은 의존성 취약점 검사를 대신하지 않는다.
