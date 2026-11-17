# Validation Plan, Matrix & Quality Gates

[English](../en/08-TEST-VALIDATION.md) | 한국어

## 1. 시험 구분

| 종류 | 범위 | 현재 상태 |
|---|---|---|
| JDK-only core smoke | SQL rendering, bind order, identifier, allowlist, multi-DS guard | **실제 실행 PASS** |
| Spring Boot 3 mixed demo | JPA+MyBatis+JdbcTemplate, flush, rollback (H2) | **미실행** (Gradle/네트워크 없음) |
| PostgreSQL real DB | CRUD/tx/collation/time | 미실행 |
| MySQL real DB | CRUD/tx/collation/time | 미실행 |
| SQL Server real DB | CRUD/tx/collation/time | 미실행 |
| Oracle real DB | CRUD/tx/collation/time | 미실행 |
| Legacy SQL translator | Parser + safe rewrite + result equivalence | 미구현 |
| Load benchmark | p50/p95 overhead | 미실행 |

## 2. 테스트 매트릭스

- framework: new API / JPA legacy / MyBatis legacy / JDBC legacy
- database: PostgreSQL / MySQL / SQL Server / Oracle
- operation: CRUD, JOIN, PAGE, BATCH, UPSERT, timestamps, errors
- consistency: same DS mixed, multi DS divergent, retries/rollback/isolation
- versions: DB server, JDBC driver, Boot, MyBatis, Hibernate

모든 조합을 동일 기능으로 무조건 지원한다고 주장하지 않는다. Capability 단위로 N/A를 허용한다.

## 3. 중요 Gate

1. G0: SQL 엔진·DBMS 라이선스 승인
2. G1: API/SPI core contract 통과
3. G2: 4 DBMS 실제 테스트 & 결과 매핑
4. G3: JPA/MyBatis/JDBC 기존 회귀 테스트
5. G4: 선택 변환 테스트 + 승인 증거
6. G5: 동시성/성능/취소/장애복구
7. G6: 배포/버전호환/API breaking change 평가

## 4. 증거 필드

```
requirementId, scenarioId, queryId, sqlHash, dbms, dbVersion,
driverVersion, frameworkVersion, providerVersion, schemaVersion,
testTime, inputHash, outputHash, exitCode, logsPath, reviewer
```

## 5. 실제 실행

```bash
./tools/run-core-smoke.sh
# Gradle 설치와 Maven Central 연결이 가능하면:
gradle :spring-boot-demo:test
```

## 6. 지원 선언 기준

개발용 DSL SQL 생성(문자열) 검증과 실제 DB 실행은 완전히 다른 상태. `COMPILED`, `RENDERED`, `EXECUTED`, `RESULT_VERIFIED`, `TX_VERIFIED`, `PERFORMANCE_VERIFIED`를 별도로 기록한다.
