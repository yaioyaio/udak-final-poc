# UDAK Final Architecture + Runnable POC (v0.1.0-poc)

[English](README.md) | 한국어

**UDAK: Unified Data Access & Compatibility Kit** — Spring Boot 기존 JPA / MyBatis / JdbcTemplate 유지보수와 신규 통합 데이터 접근 API를 위한 **설계 및 검증 패키지**.

> ⚠️ 이 ZIP은 제품 최종 릴리스가 아닌 **최종 목표 아키텍처와 1차 실행 POC**이다. SQL 컴파일러는 제한된 구문만 처리하고, 기존 SQL의 실제 자동 변환 엔진·4종 실DB 통합은 구현되어 있지 않다. 테스트 증거를 확인한 후 단계적으로 확장한다.

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

## 2. 핵심 제품 정책

- **Primary customer:** 여러 DBMS/프레임워크를 운영하는 Spring Boot SI/SM/기업 백엔드 팀
- **New:** 안정화 이후 Simple CRUD + Fluent Query API (현재 core는 제한된 컴파일러 SPI 데모)
- **Legacy:** 기존 소스 변경 최소화, Observe → Analyze → Approved Rewrite 순서
- **SQL engine:** 교체 가능한 `SqlCompiler`/translation SPI. 외부 엔진 채택은 라이선스·기능 검증 후
- **Transactions:** Spring이 관리하고, UDAK는 설정·위험을 감지한다. 다중 DB 원자성 보장은 하지 않는다
- **Supported target DBMS:** PostgreSQL, MySQL, SQL Server, Oracle (실DB 테스트는 차후)

## 3. 문서 길잡이

| 문서 | 내용 |
|---|---|
| [00-EXECUTIVE-DECISIONS.md](docs/ko/00-EXECUTIVE-DECISIONS.md) | 최종 목표와 기존 기술 대비 차별점 |
| [01-PRD.md](docs/ko/01-PRD.md) | 요구사항, 사용자, KPI, 범위 |
| [02-ARCHITECTURE.md](docs/ko/02-ARCHITECTURE.md) | 논리·배포 구조, 의존성, ADR |
| [03-API-SPEC.md](docs/ko/03-API-SPEC.md) | New API, Compiler/Executor/Guard 계약 |
| [04-DBMS-COMPATIBILITY.md](docs/ko/04-DBMS-COMPATIBILITY.md) | 네 DBMS 전략, SQL 의미 차이 |
| [05-LEGACY-COMPATIBILITY.md](docs/ko/05-LEGACY-COMPATIBILITY.md) | JPA/MyBatis/JDBC 적용과 승인 변환 |
| [06-TRANSACTION-CONSISTENCY.md](docs/ko/06-TRANSACTION-CONSISTENCY.md) | 로컬/다중DB 트랜잭션 및 시간 정책 |
| [07-SECURITY-OBSERVABILITY.md](docs/ko/07-SECURITY-OBSERVABILITY.md) | 보안·로깅·운영 지표 |
| [08-TEST-VALIDATION.md](docs/ko/08-TEST-VALIDATION.md) | 테스트 매트릭스·증거·품질 게이트 |
| [09-WBS-ROADMAP.md](docs/ko/09-WBS-ROADMAP.md) | Phase, 선행관계, 작업 항목 |
| [10-USECASES-EVENTSTORMING.md](docs/ko/10-USECASES-EVENTSTORMING.md) | UseCase / EventStorming |
| [11-API-CONFIG-SCHEMA.md](docs/ko/11-API-CONFIG-SCHEMA.md) | Spring 설정 계약 및 구성 예시 |
| [12-MIGRATION-RUNBOOK.md](docs/ko/12-MIGRATION-RUNBOOK.md) | 기존 프로젝트 도입·롤백 절차 |
| [13-AGENT-DEVELOPMENT-GUIDE.md](docs/ko/13-AGENT-DEVELOPMENT-GUIDE.md) | Codex / Claude Code 공통 지침 |
| [14-POC-RESULTS.md](docs/ko/14-POC-RESULTS.md) | 실제 검증 사실과 미검증 항목 |
| [15-MARKET-VS-EXISTING.md](docs/ko/15-MARKET-VS-EXISTING.md) | 기존 라이브러리 비교·제품화 판단 |
| [16-TRACEABILITY.md](docs/ko/16-TRACEABILITY.md) | 요구↔코드↔테스트 매핑 |
| [17-SQL-ENGINE-EVALUATION.md](docs/ko/17-SQL-ENGINE-EVALUATION.md) | Phase 1 엔진·라이선스 선택과 한계 |

문서는 같은 파일명을 사용해 `docs/en/`과 `docs/ko/`에서 한 쌍으로 관리한다. 내용 변경 시 두 언어를 함께 갱신하고 요구 ID·명령·버전·검증 상태를 동일하게 유지한다. 메인 `README.md`는 영문이며 한국어는 `README-KO.md`에 둔다.

## 4. 프로젝트 모듈

- `core/`: 순수 Java, 외부 의존성 없는 SPI + 제한된 SQL Dialect + 정책 검사 **실행 가능**
- `spring-boot-demo/`: Spring Boot 3.5.16 + JPA + MyBatis + JDBC + H2 예제 **코드 제공, 이 환경에서 Gradle 검증 미실시**
- `sql-jsqlparser/`: Core 밖의 고정 JSqlParser 5.4 검증 어댑터 — **파서/SPI 계약 통과, SQL 변환·실DB 지원 주장은 제외**
- `tools/`: 실행 스크립트
- `evidence/`: 실제 통과한 테스트 출력
- `docs/en/`: 영문 문서
- `docs/ko/`: 한국어 문서

## 5. 환경과 버전

- Java 17+ (JDK 21에서도 코어를 `--release 17`로 빌드)
- Spring Boot 3.5.16 (데모의 보수적 선택), Spring Boot 4.1.2는 별도 Starter 검증 트랙
- MyBatis Starter 3.0.5 (Boot 3 라인, 버전 좌표는 실제 Gradle 의존성 해석 때 확인 필요)
- Gradle 8.14+ 권장. Gradle Wrapper 스크립트·설정·jar를 포함한다. 의존성 해석과 데모 실행은 아직 검증하지 않았다

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
