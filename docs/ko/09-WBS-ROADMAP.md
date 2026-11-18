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
| Phase 3 | 스키마 변경 영향과 쿼리별 실DB 검증 | 스키마 변경에 영향받는 쿼리·테스트 ID를 연결한다. 쿼리와 검증 대상 DBMS/드라이버 조합별로 실DB 실행 증거를 기록한다. | 계획 |
| Phase 4 | DB/드라이버 취소·복구 | 제한된 계획으로 검증 대상 DB/드라이버 조합의 타임아웃·중단 시 취소와 복구를 검증한다. 커넥션 재사용과 트랜잭션 결과를 기록한다. | 계획 |
| Phase 5 | 승인·취소 이력 | 쿼리, fingerprint, 버전, 증거와 연결된 승인·취소 이력을 보존한다. 취소된 승인으로 이후 Rewrite를 실행할 수 없는지 검증한다. | 계획 |
| Phase 6 | 배포와 지원 증거 | G0/G5를 완료하고 배포물을 서명·게시한다. 실제 JDK 17에서 전체 혼합 데모를 실행하고 검증 매트릭스에 따라 DB 지원을 인증한다. | 계획 |
