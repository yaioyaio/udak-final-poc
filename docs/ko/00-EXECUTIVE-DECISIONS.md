# UDAK 최종 의사결정 (2026-11-17)

[English](../en/00-EXECUTIVE-DECISIONS.md) | 한국어

## 제품의 정체성

UDAK는 **Spring Boot Data Access Compatibility & Modernization Kit**이다. 범용 ORM 대체제가 아니다. 신규 통합 API는 선택적으로 제공하고, 핵심은 기존 JPA/MyBatis/JdbcTemplate 프로젝트의 SQL·트랜잭션·DBMS 차이를 **발견, 분석, 검증, 제한적으로 개선**하는 것이다.

## 왜 만드는가

| 기존 도구 | 강점 | UDAK 기회 |
|---|---|---|
| JPA/Hibernate | 객체 영속성, 트랜잭션 | 혼용 시 flush/cache/data source 위험 분석 |
| MyBatis | SQL 제어, Mapper XML | 여러 DBMS에 흩어진 SQL 인벤토리·변경 추적 |
| Spring JdbcTemplate | 안정적인 JDBC 실행 | SQL 정책·감사·호환성 검사 연계 |
| jOOQ | 타입 안전 DSL, Dialect | 레거시 세 프레임워크 통합 분석/승인 체계 |

## 제품 우선순위

1. **Legacy Observe/Analyze** — 기존 소스 영향 최소화
2. **Transaction & Consistency Guard** — 실수 방지. 안정성 보장 주장 금지
3. **Verified Rewrite** — Allowlist / 증거 기반 / 기본 차단
4. **Simple & Fluent New API** — 필요할 때 채택
5. CLI / CI / IDE / MCP — 확장

## 명시적 비목표

- 모든 SQL 자동 변환, 자체 범용 SQL Parser, 자체 ORM, XA Transaction Manager 구현
- JPA/MyBatis/JDBC 실행 순서의 무조건 동일화
- DBMS간 모든 동시성/시간/비교정렬의 의미적 동등성 보증

## 아키텍처 결정 (ADR)

| ID | 결정 | 근거 |
|---|---|---|
| ADR-001 | Core에서 Spring/Hibernate/MyBatis 금지 | 의존성/호환성 격리 |
| ADR-002 | Compiler SPI 중심 | 외부 엔진 전환 가능 |
| ADR-003 | Default Observe + Rewrite Deny | 레거시 사고 예방 |
| ADR-004 | 단일 DataSource 로컬 트랜잭션 우선 | 분산 원자성 오해 방지 |
| ADR-005 | 네 DBMS 실제 통합 테스트 통과 전에 지원 완료 표기 금지 | 오인 방지 |
| ADR-006 | Boot3/Boot4 Starter 분리 | 메이저 호환성 유지 |
| ADR-007 | SQL 엔진 라이선스 승인 전 배포 금지 | 법적/사업적 리스크 |
| ADR-008 | SQL 승인 시 SQL/스키마/엔진/테스트 버전 연동 | 변경 시 승인 무효화 |

## 출시 판단

POC에서 SQL 분석의 실질 효용, 레거시 침투 비용, 신규 DSL 코드량 대비 이점, 실제 트랜잭션 회귀 테스트 결과를 수치화한다. 이점이 불명확하면 신규 API를 축소하고 레거시 분석/검증에 집중한다.
