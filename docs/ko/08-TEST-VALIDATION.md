# Validation Plan, Matrix & Quality Gates

[English](../en/08-TEST-VALIDATION.md) | 한국어

## 1. 시험 구분

| 종류 | 범위 | 현재 상태 |
|---|---|---|
| JDK-only core smoke | SQL rendering, bind order, identifier, allowlist, multi-DS guard | **실제 실행 PASS** |
| Spring Boot 3 mixed demo | JPA+MyBatis+JdbcTemplate, flush, rollback (H2) | 전체 Boot/Gradle은 **NOT RUN**; 업무 소스의 프로그램 방식 G3 PASS |
| PostgreSQL real DB | CRUD/tx/collation/time | PASS: minimal G2; timezone/collation NOT RUN |
| MySQL real DB | CRUD/tx/collation/time | PASS: minimal G2; timezone/collation NOT RUN |
| SQL Server real DB | CRUD/tx/collation/time | PASS: minimal G2; timezone/collation NOT RUN |
| Oracle real DB | CRUD/tx/collation/time | PASS: minimal G2; timezone/collation NOT RUN |
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

## 실제 G2 최신 증거

[최소 기능 G2](20-MANAGED-G2-RESULTS.md): 실제 네 DBMS 40개 검사·fixture 정리 PASS. SQL Server 네이티브 플랫폼 인증·정상 종료/재시작 복구, 전체 시간대/collation 동등성 및 성능은 NOT RUN이다.

## Phase 3 G3 최신 증거

[PHASE3-GATE.json](../../evidence/PHASE3-GATE.json): Core 74·Observe Core 202·어댑터 계약 188, H2 동일 DS 10개·실DB 4종 40개 호환성 항목 PASS. 기존 demo의 4개 업무 소스를 programmatic Spring/Hibernate/MyBatis 경로로 재사용했으며 Boot 전체 자동 구성과 Gradle task 실행은 NOT RUN이다. [세부 결과와 제외 범위](21-LEGACY-OBSERVE-RESULTS.md)를 따른다. 부하·성능 검증은 실행하지 않았다.
