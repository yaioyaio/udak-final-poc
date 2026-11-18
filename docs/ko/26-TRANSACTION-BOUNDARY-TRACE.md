# 트랜잭션 경계 추적

[English](../en/26-TRANSACTION-BOUNDARY-TRACE.md) | 한국어

제품 확장 Phase 2는 Spring Framework 6.2.19 로컬 트랜잭션을 명시적으로 추적한다. 설정한 JPA/Hibernate, MyBatis, JdbcTemplate 훅의 SQL 관측을 Spring 트랜잭션 경계와 연결한다. 요구 사항과 검증 계획은 [16-TRACEABILITY.md](16-TRACEABILITY.md)에서 확인할 수 있다.

## 적용 방법

1. 설정한 `DataSource`와 선택 사항인 `EntityManagerFactory`로 `SpringTransactionTrace`를 만든다. `new SqlObserver(trace)`로 추적기를 관측 싱크로 전달하고, 해당 옵저버를 [기존 명시적 Observe 훅](21-LEGACY-OBSERVE-RESULTS.md)에 연결한다.
2. 애플리케이션 초기화 시 `trace.registerWith(manager)`로 지원되는 JDBC 또는 JPA 매니저에 리스너를 연결한다. 이 매니저가 새 로컬 트랜잭션을 시작하면 추적을 등록한다. `trace.checkpoint()`를 트랜잭션 안에서 호출하면 이미 추적 중인 경계에 체크포인트를 남긴다.
3. 애플리케이션이 수행한 JPA flush가 성공적으로 반환한 뒤 이벤트 순서에 그 위치를 남기려면 `trace.markFlushCompleted()`를 호출한다.
4. 추적할 작업과 완료 콜백이 끝난 뒤 `trace.snapshot()`을 호출한다. 불변 스냅샷에는 기록된 이벤트와 수집 상한·경합 또는 진단 오류로 누락된 건수가 포함된다.

```java
var trace = new SpringTransactionTrace(dataSource, entityManagerFactory);
trace.registerWith(transactionManager);
var observer = new SqlObserver(trace);
```

## 추적 결과 해석

| 관측 항목 | 의미 |
|---|---|
| 추적 등록 | `ATTACHED`는 등록된 Spring 매니저가 새 트랜잭션을 성공적으로 시작한 뒤 추적이 연결된 시점을 기록한다. 같은 Spring 경계에서 체크포인트를 반복하면 해당 경계를 재사용한다. `REQUIRED` 선언 여부는 별도 근거로 확인해야 한다. |
| SQL 연결 | 설정한 자원과 현재 스레드에 바인딩된 자원 홀더의 객체 동일성을 확인한다. 트랜잭션 밖, 미등록, 외부 자원 관측을 구분한다. 연결은 Spring 경계와의 연관성을 뜻한다. `BEFORE_COMPLETION` 기록 뒤의 SQL은 기존 홀더가 남아 있어도 해당 경계와 연결하지 않는다. SQL 실행 성공과 물리 커넥션의 동일성은 별도 근거로 확인해야 한다. 연계 이벤트의 매니저 유형은 `JDBC` 또는 `JPA`, 미연계 이벤트는 `NONE`으로 표시한다. |
| 중단과 재개 | 독립 작업이 실행되는 동안 Spring의 중단·재개 콜백으로 외부 경계의 상태를 기록한다. 등록된 매니저가 시작한 내부 경계는 자체 ID와 완료 결과를 가진다. |
| Savepoint와 롤백 요청 | Savepoint 콜백은 생성 시점을 기록한다. 롤백 콜백은 실제 롤백 동작 전에 호출되어 요청을 기록한다. 롤백이 완료됐는지는 별도 근거로 확인해야 한다. |
| 명시적 flush | 호출자가 성공을 알린 flush를 표시하고 SQL 관측과의 순서를 기록한다. |
| 완료 | `COMMITTED`, `ROLLED_BACK`, `UNKNOWN`은 Spring이 제공한 완료 상태를 반영한다. 완료 기록이 없는 경계는 대기 중으로 해석한다. 대기 중인 경계나 누락된 이벤트가 있으면 스냅샷은 부분 기록이다. |

Spring 매니저의 시작 알림과 트랜잭션 동기화 콜백을 사용한다. [TransactionExecutionListener API](https://docs.spring.io/spring-framework/docs/6.2.x/javadoc-api/org/springframework/transaction/TransactionExecutionListener.html) · [TransactionSynchronization API](https://docs.spring.io/spring-framework/docs/6.2.x/javadoc-api/org/springframework/transaction/support/TransactionSynchronization.html)

추적은 명시적 연결을 통해 현재 스레드의 기존 실행을 관찰한다. SQL 실행, flush, 트랜잭션 동작은 애플리케이션과 Spring이 관리한다. 보고서에는 원본 SQL, 바인드 값, 트랜잭션 이름, 연결 주소, savepoint 객체, 예외 원문을 포함하지 않는다. 추적기는 디버그 로그를 출력하지 않는다.

## 검증

```bash
python3 tools/run-tx-trace.py
```

| 요구 ID | 검증 범위 | 상태 |
|---|---|---|
| TXTRACE-001 | 명시적 등록, 자원 연결, 연결되지 않은 관측, 수집 상한과 불변 메타데이터 | PASS |
| TXTRACE-002 | Spring/H2에서 JPA/Hibernate, MyBatis, JdbcTemplate 혼용, commit과 rollback-only, `REQUIRES_NEW`, JDBC savepoint, flush 순서와 완료 불명 | PASS |
| TXTRACE-003 | 고정 의존성, 보호 실행기, Core/Observe/Guard 회귀, 한·영 문서, 성공·실패 정리와 메타데이터 증거 | PASS |

검증 범위는 H2를 사용하는 동기 Spring 로컬 트랜잭션이다. 이번 단계의 전체 Boot 컨텍스트와 대상 4종 DBMS 추적 검증 상태는 NOT RUN이다. XA, 비동기 전파, 전역 자동 래핑은 범위 밖이다.

## 실제 검증 결과

보호 실행 9단계와 신규 Spring/H2 추적 시나리오 8개·단언 318개가 통과했다. 실제 혼용 테스트에서는 세 접근 경로가 같은 로컬 경계에 연결됐고, flush 전후 MyBatis의 가시성과 최종 커밋 데이터를 확인했다. `REQUIRES_NEW`는 외부 트랜잭션이 롤백된 뒤에도 내부 커밋이 유지됐다. JDBC savepoint 롤백 후 바깥 트랜잭션은 독립적으로 커밋했다. `UNKNOWN` 검사는 H2 커밋 직후 응답 실패를 주입해 Spring 완료 상태와 실제 데이터 상태가 다를 수 있음을 재현했다. 외부 매니저의 보조 홀더로 경계를 잘못 등록하지 않는 경우와 별도 스레드도 검사했다. 다른 완료 콜백이 `REQUIRED` 조회를 시작할 때 이전 경계에 잘못 연결되는 현상을 재현하고 수정 후 미연계를 확인했다. [실행 증거 및 타임라인](../../evidence/TX-TRACE-VALIDATION.json)

기존 H2 레거시·Guard 회귀 각 10개, Observe·어댑터·Spring Guard 계약과 Core smoke를 통과했다. 실행 임시 파일 157개·38,148,035바이트는 자동 정리되어 잔여 0개다. 새 컨테이너는 0개이며 기존 관리 DB 12개는 정지 상태를 확인했다. 이번 보호 실행은 Java 17 대상으로 컴파일했다. 독립 Gradle 빌드, 운영 부하 및 실제 4종 DB 추적은 NOT RUN이다.

다음은 확장 Phase 3이다. 스키마 변경을 Phase 1의 Query ID와 테스트에 연결하고, 영향받는 쿼리별로 대상 DBMS·드라이버에서 결과와 Java 매핑을 검증한다. [로드맵](09-WBS-ROADMAP.md#제품-확장-단계)
