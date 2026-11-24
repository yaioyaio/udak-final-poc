# Work Breakdown Structure (WBS) + PLAN / TASK / TODOLIST

[English](../en/09-WBS-ROADMAP.md) | 한국어

추정 기간은 인력/라이선스/테스트 인프라에 크게 좌우되므로 **확정 일정이 아님**. 각 Phase는 이전 Gate 통과 후 진행.

| Phase | Task ID | 작업 | 선행 | 산출물/AC |
|---|---|---|---|---|
| 0 | T-001 | 제품 차별성/수요 검증 | - | 고객 시나리오 5건 |
| 0 | T-002 | jOOQ/Calcite/JSqlParser 기능·라이선스 PoC | - | 4개 DB 상용 사용 가능성 보고 |
| 1 | T-003 | Java Core, SPI 설계 | T-002 | 컴파일/교체 계약 테스트 |
| 1 | T-004 | Schema metadata/identifier policy | T-003 | 인젝션/식별자 테스트 |
| 1 | T-005 | Dialect capability | T-003 | 명시적 미지원 처리 |
| 2 | T-006 | Simple CRUD API | T-003 | CRUD 계약 |
| 2 | T-007 | Fluent Query DSL | T-003 | JOIN/PAGE 계약 |
| 2 | T-008 | Spring-aware JDBC executor | T-006 | 로컬 트랜잭션 테스트 |
| 3 | T-009 | PostgreSQL/MySQL 실DB 검증 | T-008 | SQL/result evidence |
| 3 | T-010 | SQL Server/Oracle 실DB 검증 | T-008 | driver/license evidence |
| 4 | T-011 | JDBC Legacy Observe | T-008 | 업무코드 불변 |
| 4 | T-012 | MyBatis Legacy Observe | T-011 | BoundSql/mapper 추적 |
| 4 | T-013 | JPA Legacy Observe | T-011 | Hibernate 변경 없음 |
| 4 | T-014 | Tx/Consistency Diagnostics | T-011 | flush/cache/DS 위험 보고 |
| 5 | T-015 | SQL parser/translator SPI | T-002 | unsupported fail closed |
| 5 | T-016 | Approval Registry/Evidence | T-015 | 버전 변경시 무효화 |
| 5 | T-017 | SQL rewrite per query | T-016 | 실제 DB 동등성 테스트 |
| 6 | T-018 | Boot3 Starter/AutoConfig | T-011 | 샘플 앱 통과 |
| 6 | T-019 | Boot4 Starter/AutoConfig | T-018 | Boot4 별도 호환 |
| 6 | T-020 | Observability/CI/release | T-017 | 품질/성능 게이트 |
| 6–7 | T-021 | Phase 6 읽기 전용 CLI inspect, Phase 7 MCP | T-020 | 읽기 전용 증거 감사 |

## Task 실행 템플릿

```markdown
TASK-ID:
Linked Requirement:
Architecture/ADR:
Inputs:
Implementation Files:
Tests:
DBMS/Framework Matrix:
Security & Consistency Risks:
Evidence path:
Status: TODO / IN_PROGRESS / BLOCKED / VERIFIED
```

## TODO (실제 현재 상태)

- [x] JDK Core SQL Compiler SPI/POC
- [x] ID allowlist 및 bind ordering smoke test
- [x] 승인 변환 정책 게이트(변환 엔진 아님)
- [x] 복수 DataSource 구성 guard (정적 테스트)
- [x] Spring Boot 혼합 예제 소스 작성
- [ ] Spring Boot 혼합 예제 Gradle 빌드·실행·테스트
- [x] 최소 CRUD/Query API·실제 Spring JDBC/H2 계약
- [x] 4 DBMS 전용 fixture·driver/provider·metadata 검증 기반
- [x] 실제 네 DBMS provider/driver 구성과 최소 기능 G2 (40개 검사)
- [x] Legacy Observe 실제 어댑터(3개 경로 검증)
- [x] 명시적 트랜잭션 진단과 Spring/H2 계약 검사 (T-014 한정)
- [x] Phase 5 제한 Parser/Translator Provider 로컬 계약
- [x] Phase 5 4종 실DB 고정 fixture 동등성과 G4
- [x] Phase 6 Starter·CLI·보호 로컬 검증
- [ ] G5 동시성·성능·취소·복구 검증

## 사용자 확정 6단계와 현재 진행

| 단계 | 범위 | 현재 상태 |
|---|---|---|
| Phase 1 | SQL Compiler SPI, 외부 라이브러리 비교·연동·선택 artifact 라이선스 검증 | 요청 범위 PASS; [실행 증거](../../evidence/PHASE1-VALIDATION.json) |
| Phase 2 | 최소 신규 API·JDBC executor·4 DBMS 실환경 검증 | 최소 API·Executor·실제 4종 최소 기능 G2 PASS; 다음은 Phase 3 Observe |
| Phase 3 | JPA·MyBatis·JdbcTemplate Observe/Analyze | PASS: 계약 검사 202 / 188개; H2 10개 + 실DB 40개 항목; 다음 Phase 4 |
| Phase 4 | Transaction & Consistency Guard 고도화 | PASS: 명시적 구성·현재 스레드 정책 및 Spring/H2 계약 (T-014 한정) |
| Phase 5 | 검증·승인 SQL 선택 변환 | G4 PASS (고정 fixture) |
| Phase 6 | Boot3/Boot4 Starter, 읽기 전용 CLI, 로컬 CI, 배포 게이트 | 로컬 CI / G6 비공개 후보 PASS, 정식 배포 BLOCKED |

위 표는 사용자 단계에 맞춘 실행 묶음이며 기존 Task ID와 상세 선행관계는 유지한다. T-001 고객 수요와 T-002의 실DB·driver별 상용 조건/제품 배포 승인은 이 기술 PoC만으로 완료 처리하지 않는다. [엔진 비교](17-SQL-ENGINE-EVALUATION.md)와 [현재 결과](14-POC-RESULTS.md)의 검증 범위를 따른다.

Phase 2 완료 근거는 [관리형 G2 결과](20-MANAGED-G2-RESULTS.md)를 따른다. T-007 전체 Fluent JOIN, 상용 배포 승인·지원 인증을 이 최소 기능 검증으로 완료 처리하지 않는다.

Phase 5의 제한 변환 구현·검증 범위는 G4로 완료했다. Phase 6은 별도 Boot3·Boot4 Starter, 읽기 전용 CLI, 로컬 CI를 다룬다. GitHub Actions는 금지한다. 정식 배포는 BLOCKED다. [Phase 5 결과](23-SELECTIVE-REWRITE-RESULTS.md) · [Phase 6 범위](24-STARTERS-CLI-RELEASE-GATES.md)

## 제품 확장 단계

기존 POC 단계와 게이트 증거를 바탕으로 확장한다. 확장 단계별로 완료 기준을 적용한다.

| 확장 단계 | 범위 | 완료 기준 | 상태 |
|---|---|---|---|
| Phase 1 | SQL 인벤토리와 PR 변경 보고서 | 실제 Observe 어댑터 3개에서 메타데이터를 수집하고 명시적 쿼리 정의와 테스트 커버리지를 기록한다. 로컬 PR 보고서에서 base/head 스냅샷을 비교한다(`INV-001`–`INV-003`). | PASS. [SQL 인벤토리 가이드](25-SQL-INVENTORY-PR-REPORT.md). |
| Phase 2 | 트랜잭션 경계 추적 | JPA, MyBatis, JdbcTemplate의 SQL 관측을 Spring Framework 6.2.19 로컬 트랜잭션 경계와 연결하고 H2에서 보고를 검증한다(`TXTRACE-001`–`TXTRACE-003`). | PASS (8 scenarios). [트랜잭션 경계 추적](26-TRANSACTION-BOUNDARY-TRACE.md). |
| Phase 3 | 스키마 변경 영향과 쿼리별 실DB 검증 | 정규화된 컬럼 변경을 인벤토리 쿼리·테스트 해시와 연결한다. PostgreSQL 17과 MySQL 8.0에서 각각 영향 대상 쿼리 두 개를 검증한다(`SCHEMA-001`–`SCHEMA-003`). | PASS (4 combinations). [스키마 영향 분석과 회귀](27-SCHEMA-IMPACT-REGRESSION.md). |
| Phase 4 | DB/드라이버 취소·복구 | 대상 DB/드라이버 조합에서 JDBC 명시 취소, 쿼리 타임아웃, 커밋 전 세션 단절 후 복구를 검증한다. 물리 세션 재사용과 트랜잭션 결과를 기록한다(`RECOVERY-001`–`RECOVERY-003`). | PASS (PostgreSQL과 MySQL, 6건). [취소와 복구](28-DB-CANCELLATION-RECOVERY.md). |
| Phase 5 | 승인·폐기 이력 | 쿼리, fingerprint, 버전, 증거와 연결된 승인·폐기 이력을 보존한다. 폐기된 승인으로 이후 Rewrite를 실행할 수 없는지 검증한다(`APPROVAL-001`–`APPROVAL-003`). | PASS (Core와 H2/JDBC). [쿼리별 승인·폐기 이력](29-QUERY-APPROVAL-HISTORY.md). |
| Phase 6 | 배포와 지원 증거 | G0/G5를 완료하고 배포물을 서명·게시한다. 실제 JDK 17에서 전체 혼합 데모를 실행하고 검증 매트릭스에 따라 DB 지원을 인증한다. | 승인 범위의 G0 후보, G5 1차 시험, 혼합 데모, 로컬 서명 PASS. 정식 배포 BLOCKED, 제품 지원 NOT CERTIFIED. [증거와 남은 게이트](30-RELEASE-SUPPORT-EVIDENCE.md). |

## 기능 우선 백로그

2026-11-21 결정에 따라 제품 기능 완성을 우선하고 공개 배포 준비를 보류한다. 다음 작업은 기존 게이트 증거를 바탕으로 진행한다. [차기 작업 핸드오프](33-FEATURE-HANDOFF.md)

| 순서 | 작업 | 상태 | 범위와 인수 조건 |
|---|---|---|---|
| 1 | NEXT-001 · Core 문자열 출력 정제 | PASS | `Bind`, `CompiledQuery`, `QueryDefinition`의 문자열 출력은 안전한 메타데이터로 제한된다. 보호 Core 스모크에서 합성 표식 미노출, 전달한 값 객체의 `toString()` 미호출과 기존 바인딩 계약을 확인했다. |
| 2 | NEXT-002 · MyBatis Mapper XML 인벤토리와 PR 보고서 | PASS | 선택형 base/head 보고서가 XML 추가·변경·삭제와 동적 치환 후보를 파일·줄·분류·해시로 보여 준다. 로컬 테스트에서 미지원 사례와 외부 해석 차단을 확인했다. [Mapper XML 검토](25-SQL-INVENTORY-PR-REPORT.md#선택형-mapper-xml-검토-next-002) |
| 3 | NEXT-003 · 레거시 Observe 적용과 커버리지 | PASS | Hibernate 명시적 합성의 H2 OFF/ON 대조에서 업무 결과·롤백·관측 이벤트를 검증했다. 고정 `UNAVAILABLE` 사유별 집계가 Observe·인벤토리·보고서 검증을 통과했다. [합성 결과](21-LEGACY-OBSERVE-RESULTS.md#기존-hibernate-inspector-합성-next-003) |
| 4 | NEXT-004 · 스키마 계약과 환경 drift | PASS (H2) | 지정 테이블 메타데이터를 읽고 같은 리비전의 정규화 스냅샷을 비교한다. H2에서 컬럼 변경 5종을 검증했다. 외부 DBMS 검증은 NOT RUN이다. 독립 주문 회귀에서 영향받는 시험 한 건을 선정했고 미사용 컬럼 대조군은 제외했다. H2의 마이그레이션 이력과 관측 변경을 대조해 일치·미해결을 검증했다. 검토된 정적 감사 SQL 두 문장이 일치했고 인벤토리 항목 4개 중 1개를 완전히 자동 추출했다. 렌더링된 재고 UPDATE 두 분기는 검토된 참조와 일치했다. `active` 변경은 ON 경로만, 미사용 컬럼 변경은 0건을 선정했다. 한 Query ID에서 관측된 두 지문 중 영향받는 ON 시험만 선정했고 지문별 의존성 누락은 INCOMPLETE로 남겼다. v2 인벤토리에 지문별 실제 테스트를 기록하며 같은 Query ID의 연결 뒤바뀜을 탐지했다. PR 보고서는 지문별 관측 테스트 연결의 추가·삭제를 표시한다. 주문 파일럿은 PR 보고서의 영향 테스트 해시를 등록된 재실행 진입점에 연결하고 불완전 증거를 표시한다. 한 PR 보고서에서 재고 OFF·ON을 선정하고 각각 스키마 해시를 확인한 H2에서 재실행했다. [영향 테스트 해시를 주문 회귀 테스트에 연결](25-SQL-INVENTORY-PR-REPORT.md#영향-테스트-해시를-주문-회귀-테스트에-연결) [PR에서 지문별 관측 테스트 연결 검토](25-SQL-INVENTORY-PR-REPORT.md#pr에서-지문별-관측-테스트-연결-검토) [지문을 관측한 테스트 연결 검증](27-SCHEMA-IMPACT-REGRESSION.md#지문을-관측한-테스트-연결-검증) [관측된 지문별 의존성 검증](27-SCHEMA-IMPACT-REGRESSION.md#관측된-지문별-의존성-검증) [재고 UPDATE 회귀](27-SCHEMA-IMPACT-REGRESSION.md#렌더링된-주문-재고-update-의존성-검증) [스키마 계약](27-SCHEMA-IMPACT-REGRESSION.md#환경-간-스키마-계약-비교) |
| 5 | NEXT-005 · 도입 지원과 가치 검증 | PASS (합성 H2) · 외부 PostgreSQL 파일럿 PASS · 담당자 직접 검토 PASS | 사용자 지정 H2 주문 서비스의 OFF/ON 업무 결과와 롤백 비교를 통과했다. PR 보고서에서 재고 SQL 변경 한 건의 두 관측 근거를 함께 표시한다. H2 진단 예제에서 성공한 SQL의 정규화 불가와 MyBatis 캐시 적중을 구분했다. 운영 레거시 적용 NOT RUN. [파일럿 결과](34-LEGACY-ADOPTION-PILOT.md#독립-주문-서비스-파일럿) ThingsBoard CE 체크아웃을 고정하고 공식 Maven 아티팩트를 검증했다. 격리 PostgreSQL에서 기존 두 테스트의 Observe OFF/ON을 통과했다. 실제 상류 SQL 변경이 탐지됐고 UUID 대조군 변경은 0건이었다. 검증된 캐시에서 설정 16.368초와 직접 확인을 포함한 검증 45.044초를 기록했다. [ThingsBoard 도입 검토](34-LEGACY-ADOPTION-PILOT.md#thingsboard-도입-검토) |

공개 저장소·네임스페이스·운영 서명·게시 작업은 **DEFERRED**다. 공식 성능 시험과 남은 DB 지원 검증은 문서화된 환경·승인 조건에 따라 진행한다. [남은 배포·지원 게이트](30-RELEASE-SUPPORT-EVIDENCE.md) · [제품 G5 기준](32-PRODUCT-G5-ACCEPTANCE.md)
