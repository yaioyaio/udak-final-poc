# Transaction & Consistency Guard — 안전성 계약

[English](../en/06-TRANSACTION-CONSISTENCY.md) | 한국어

## 절대적 보장 범위

UDAK가 모든 트랜잭션·시간 어긋남 문제를 방지하는 것은 불가능하다. **진단 / 제한된 실행 규칙 / 계약 테스트**를 제공한다.

## 1. 단일 DataSource

- JPA + JDBC/MyBatis를 같은 로컬 트랜잭션에 참여시키려면 Spring-managed DataSource와 호환되는 TransactionManager 설정 필요.
- MyBatis는 MyBatis-Spring 관리 `SqlSession` 경로 사용.
- JPA dirty checking은 보류된 변경을 DB에 보여주지 않으므로 SQL 혼용 전 필요 시 `EntityManager.flush()`.
- JDBC/MyBatis 변경 후 JPA가 가진 동일 Entity는 오래된 상태일 수 있어 `refresh`/`clear`/영속성 경계 재설계 필요.
- SQL execution order와 flush 순서는 설정만으로 완전 자동화할 수 없다.

### 테스트 시나리오

1. JPA insert → flush → MyBatis read → JdbcTemplate read: 동일 값
2. JPA insert → JdbcTemplate update → RuntimeException: 양쪽 모두 rollback
3. JDBC update → JPA cached entity read: stale cache 위험 재현 및 대응 검증
4. `REQUIRES_NEW`, `readOnly`, `timeout`, `isolation` 조합 테스트

## 2. 서로 다른 DataSource

- 일반 `@Transactional` 한 번으로 여러 DB 원자적 commit 보장 안 됨.
- 단일 로컬 트랜잭션 범위를 초과하는 구성은 시작 시 진단·경고 또는 policy block.
- 실제 원자성 필요: JTA/XA + DB/driver 호환 검토.
- 마이크로서비스 및 비동기 통합: Outbox + Saga + idempotency + reconciliation.
- 외부 시스템 장애 시 재시도는 멱등·경계 명확한 작업만.

## 3. 시간 정책

- Instant는 절대 시각을 나타냄. LocalDateTime은 타임존 없음.
- JDBC/DB 세션 타임존 및 DB 컬럼 타입을 명시적 계약으로 지정.
- DB/애플리케이션 서버의 시계는 NTP 등 운영 시스템에서 동기화.
- Date/Time 결과 비교는 정밀도(마이크로/나노), DST, timezone 변환까지 검사.

## 4. Timeout policy

- transaction timeout, query timeout, socket timeout, connection acquisition timeout은 서로 다름.
- 타임아웃이 발생했다고 실제 서버 쿼리가 즉시 취소되었다는 보장 없음.
- DBMS 취소/commit 상태가 불확실한 경우 무조건 재시도 금지.

## 5. 진단 등급 (UDAK 제안)

| Level | 증거 |
|---|---|
| T0 | DataSource/TxManager configuration scan |
| T1 | 단일 DS commit/rollback 테스트 |
| T2 | JPA+MyBatis+JDBC 혼용 Flush/cache 테스트 |
| T3 | 다중 DB 장애/보상/XA 검증 보고 (즉시 일치 보장 아님) |

현재 POC `ConsistencyGuard`는 **복수 DataSource 목록 감지 및 예외**만 구현. Spring 설정 자동 검사·멀티DB XA/트랜잭션 관리 기능은 미구현.

## Phase 3에서 확인한 T2 경계

단일 Spring JpaTransactionManager와 동일 DataSource에서 Hibernate/JPA·MyBatis-Spring·JdbcTemplate의 실제 연결 동일성, 명시적 dirty UPDATE flush 전후 가시성, JPA/MyBatis stale cache와 refresh/clear, 세 경로 commit/rollback을 검증했다. H2 10개·실DB 4종 40개 항목 PASS다. 이는 자동 동기화·분산 원자성·모든 propagation/isolation/timeout 조합을 보장하지 않는다. 다음 Phase 4는 DataSource/TransactionManager 설정·전파/readOnly/격리/시간 제한의 진단을 고도화한다. [증거와 미검증 범위](21-LEGACY-OBSERVE-RESULTS.md).
