# PRD — Product Requirements Document

[English](../en/01-PRD.md) | 한국어

## 1. 사용자와 문제

### 페르소나
- P-01 SI/SM Spring Boot 개발자: Oracle/MyBatis XML과 최신 JPA를 함께 유지보수
- P-02 여러 DBMS를 지원하는 제품 개발자: 고객사 PostgreSQL/MySQL/SQL Server/Oracle 대응
- P-03 DBA/아키텍트: SQL·트랜잭션 품질 표준화 및 변경 영향 분석
- P-04 DevOps/QA: 테스트 결과·승인 기록·성능 회귀 추적

### Jobs To Be Done
- 복잡한 JPA/MyBatis/JDBC 코드를 변경하기 전 SQL 및 실행 경계 위험을 확인한다.
- DBMS 전환 시 수정 대상 SQL을 정확히 식별한다.
- 신규 프로젝트는 공통 API와 안정적인 기본값으로 시작한다.
- 변경된 SQL이 승인된 기능만 수행한다는 테스트 증거를 남긴다.

## 2. 기능 요구사항 (P0/P1/P2)

| ID | 기능 | 우선순위 | 수용 기준 |
|---|---|---|---|
| FR-001 | SQL Compiler SPI | P0 | 외부 구현체를 교체해도 Core 컴파일 |
| FR-002 | Basic CRUD/Query API | P0 | SELECT/INSERT/UPDATE/DELETE 계약 명시 |
| FR-003 | 4종 Dialect/DBMS Capability | P0 | 검증된 공통 SQL subset 테스트 |
| FR-004 | Parameter/Identifier Guard | P0 | 악의적 식별자 및 값 문자열 결합 차단 |
| FR-005 | Legacy JPA Observe | P0 | 기존 Entity/Repository 결과 동일 |
| FR-006 | Legacy MyBatis Observe | P0 | Mapper 및 ResultMap 유지 |
| FR-007 | Legacy JDBC Observe | P0 | 기존 RowMapper 유지 |
| FR-008 | SQL Fingerprint/QueryID | P0 | 코드 위치/해시 식별 가능 |
| FR-009 | Approved Rewrite Guard | P0 | 미승인/변경된 SQL 변환 차단 |
| FR-010 | Transaction Configuration Diagnostics | P0 | 복수 DS, 잘못된 tx 설정 경고/차단 |
| FR-011 | DBMS compatibility report | P1 | parse/render/execution/semantic 별 분리 |
| FR-012 | Actual rewrite engine integration | P1 | 사전 승인 SQL만 실제 변환 |
| FR-013 | Test Evidence Registry | P1 | 쿼리·스키마·엔진·대상버전 증거 연동 |
| FR-014 | Simple CRUD Facade | P1 | ORM 또는 데이터 소스별 기능 경계 문서화 |
| FR-015 | Multiple DataSources | P1 | 자원별 tx/route 명시, 자동 원자성 주장 금지 |
| FR-016 | SQL performance/observability | P1 | 개인정보 없는 metric/tag 및 trace |
| FR-017 | CI/CLI integration | P2 | 호환성/정책 검증 자동화 |
| FR-018 | MCP agent inspection | P2 | 읽기 전용 SQL 진단 도구 제공 |

## 3. MVP 제외 사항

- 실제 레거시 SQL 무제한 자동 재작성
- DBMS간 2PC/XA의 자동 구성 또는 해결
- Entity Manager 관리/Dirty checking 재구현
- 자동 데이터 동기화, CDC, 마이그레이션
- R2DBC/reactive 지원

## 4. 비기능 요구사항

| ID | 비기능 | 목표/검증 |
|---|---|---|
| NFR-01 | Fail closed | 잘못된 승인/바인딩/식별자 시 차단 |
| NFR-02 | Performance | Observe 비변환 경로 p95 +5% 이내 **목표** |
| NFR-03 | Security | SQL 파라미터 값 로그/메트릭 기본 미노출 |
| NFR-04 | Compatibility | Boot3/Boot4 별도 검증 매트릭스 |
| NFR-05 | Audit | SQL 승인 버전과 검증 증거 연결 |
| NFR-06 | Stability | 새 모듈 미사용 시 기존 서비스 동작 불변 |
| NFR-07 | Portability | SQL 공통 subset만 의미적으로 정의 |

## 5. KPI와 릴리스 조건

- 모든 P0 요구사항에 대응하는 테스트와 evidence 경로 존재
- 미지원 기능을 실제 지원으로 표시한 오류 0건
- 승인되지 않은 변환 실행 0건
- 지정 DBMS/version별 실제 환경 테스트를 통과한 기능만 릴리스 표시
- 장애 롤백(Bridge 비활성화/즉시 이전 릴리스 복원) 시나리오 검증
