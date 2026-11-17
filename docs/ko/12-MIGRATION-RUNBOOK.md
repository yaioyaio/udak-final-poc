# Legacy Migration & Operations Runbook

[English](../en/12-MIGRATION-RUNBOOK.md) | 한국어

## 단계 0 — 대상 파악

- 앱/Boot/JDK/Hibernate/MyBatis/Driver/DB 버전 수집
- DataSource 수·TransactionManager·트랜잭션 전파 확인
- Mapper XML, JPQL, Native SQL, JDBC SQL inventory
- DDL/프로시저/Hint/JSON/Date/CLOB/Sequence 의존성 확인

## 단계 1 — Baseline

- 기존 프로젝트의 단위·통합·E2E/부하 테스트 결과 보관
- SQL Query ID/Plan/평균·p95 지표 수집
- commit/rollback, flush/cache, timeout 현상을 재현

## 단계 2 — Observe only

- UDAK Bridge 설치: SQL 변경 기능 OFF
- SQL 로깅·민감정보 노출 여부 검사
- rollback/timeout/performance 회귀 확인
- 이상 발생시 Bridge 모듈 제거 또는 `enabled: false`로 즉시 복원

## 단계 3 — Analyze

- DBMS별 Syntax/Capability/Type Compatibility Report
- `SUPPORTED`, `UNSUPPORTED`, `UNKNOWN` 구분
- SQL 위험 우선순위 분류(사용 빈도/업무 중요도/복잡성)

## 단계 4 — Selective Rewrite

- 위험도가 낮은 SELECT 한 건을 선정
- SQL hash/source/target/schema/provider version 승인
- 원본·변환 모두 실 DB 테스트 및 결과 비교
- 선택적 배포, rollout/rollback 기록
- 승인 조건 변경 시 자동 비활성화

## 단계 5 — 신규 API 점진 전환

- 신규 업무는 통합 API 사용 고려
- 기존 Mapper/Entity를 무조건 재작성하지 않음
- 검증된 로직만 단계별 이관

## 실패/복구

1. SQL error 또는 result mismatch 감지
2. 해당 쿼리 승인 rule 비활성화
3. 인시던트 로그/evidence 보존
4. 이전 정상 build/config 롤백
5. 데이터 보정이 필요하면 트랜잭션/보상 계획에 따라 별도 수행
