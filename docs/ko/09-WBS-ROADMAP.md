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
| 7 | T-021 | CLI+MCP inspect | T-020 | read-only audit |

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
- [ ] 실제 SQL Parser/Translator Provider
- [ ] Starter 자동설정 및 API 성능 검증

## 사용자 확정 6단계와 현재 진행

| 단계 | 범위 | 현재 상태 |
|---|---|---|
| Phase 1 | SQL Compiler SPI, 외부 라이브러리 비교·연동·선택 artifact 라이선스 검증 | 요청 범위 PASS; [실행 증거](../../evidence/PHASE1-VALIDATION.json) |
| Phase 2 | 최소 신규 API·JDBC executor·4 DBMS 실환경 검증 | 최소 API·Executor·실제 4종 최소 기능 G2 PASS; 다음은 Phase 3 Observe |
| Phase 3 | JPA·MyBatis·JdbcTemplate Observe/Analyze | PASS: 계약 검사 202 / 188개; H2 10개 + 실DB 40개 항목; 다음 Phase 4 |
| Phase 4 | Transaction & Consistency Guard 고도화 | 정적 PoC만 존재; 기본 안전장치는 Phase 1~2부터 적용 |
| Phase 5 | 검증·승인 SQL 선택 변환 | NOT IMPLEMENTED |
| Phase 6 | Boot3/Boot4 Starter, CLI, 로컬 검증 자동화·정식 배포 | NOT IMPLEMENTED; GitHub Actions 금지 |

위 표는 사용자 단계에 맞춘 실행 묶음이며 기존 Task ID와 상세 선행관계는 유지한다. T-001 고객 수요와 T-002의 실DB·driver별 상용 조건/제품 배포 승인은 이 기술 PoC만으로 완료 처리하지 않는다. [엔진 비교](17-SQL-ENGINE-EVALUATION.md)와 [현재 결과](14-POC-RESULTS.md)의 검증 범위를 따른다.

Phase 2 완료 근거는 [관리형 G2 결과](20-MANAGED-G2-RESULTS.md)를 따른다. T-007 전체 Fluent JOIN, 상용 배포 승인·지원 인증을 이 최소 기능 검증으로 완료 처리하지 않는다.

현재 Phase 3 완료 범위와 Phase 4 착수 대상은 [Observe 결과](21-LEGACY-OBSERVE-RESULTS.md)를 따른다.
