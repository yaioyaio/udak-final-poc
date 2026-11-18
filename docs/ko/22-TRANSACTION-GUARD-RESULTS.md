# Phase 4 Transaction & Consistency Guard

[English](../en/22-TRANSACTION-GUARD-RESULTS.md) | 한국어

## 범위와 판정

명시적 구성과 현재 스레드 트랜잭션 진단 및 실제 Spring/H2 로컬 계약이 PASS다. T-014는 이 범위에서 완료했다.

요구: P4-CORE / P4-SPRING / P4-TX / P4-HARNESS, FR-010, T-014. `consistency-core`는 JDK 전용 정책·불변 enum 보고서, `consistency-spring`은 명시적 구성과 현재 스레드 진단, `consistency-testkit`은 Spring/H2 계약 검사다.

## 명시적 연결과 차단

같은 DataSource 참조와 하나의 지원 로컬 트랜잭션 매니저를 전달한다. JPA 사용 시 실제 EMF도 전달하고, MyBatis는 실제 SqlSessionTemplate을 전달한다. 사용하지 않는 선택 프레임워크 인수는 null로 둘 수 있다. 입력 목록은 방어 복사하며 참조 동일성만 비교한다. 원본 자원·매니저·풀 수명은 애플리케이션이 관리한다.

```java
import java.util.List;
import dev.udak.consistency.TransactionGuard.*;
import dev.udak.consistency.spring.SpringConsistencyGuard;

var wiring = new SpringConsistencyGuard.Configuration(
    sharedDataSource, List.of(sharedDataSource), List.of(transactionManager),
    entityManagerFactory, sqlSessionTemplate, jdbcTemplate);
SpringConsistencyGuard.inspectConfiguration(wiring).requireAllowed();

// Inside the existing Spring transaction boundary:
var intent = new Intent(true, true, true, Propagation.REQUIRED, false,
    Isolation.DEFAULT, -1, Outcome.NONE, false);
SpringConsistencyGuard.inspectTransaction(wiring, intent).requireAllowed();
```

검사는 자동으로 연결되지 않는다. `requireAllowed()` 또는 `enforce(Mode.BLOCK)`은 ERROR를 고정 메시지 예외로 차단한다. `Mode.REPORT_ONLY`는 명시적으로 진단만 수행한다. 이 예외에는 원본 객체·SQL·원인 예외를 포함하지 않는다. Starter의 자동 발견·설정 키 바인딩은 Phase 6 대상이다.

## 진단 의미와 한계

- 등록된 DS와 매니저 목록, manager/EMF/MyBatis/JdbcTemplate의 참조, SpringManagedTransactionFactory를 검사한다. 명시적으로 전달하지 않은 빈이나 다른 실행 경로를 탐색하지 않는다. 별도 wrapper·알 수 없는 매니저·확인 불가 EMF는 보수적으로 거부한다.
- snapshot은 현재 스레드의 Spring 메타데이터와 동일 참조 holder만 읽는다. actualTx와 resource binding만으로 매니저 소유·물리 연결 참여·commit 성공을 증명하지 않는다. `TRANSACTION_OWNERSHIP_UNVERIFIED` 경고를 유지한다.
- readOnly는 Spring 선언이며 DB 쓰기 금지 보장이 아니다. write 의도와 readOnly 충돌을 실행 전에 차단한다. isolation null은 UNKNOWN이며 DB 기본 격리 수준을 추정하지 않는다.
- propagation, 상위 경계 존재, 요청 isolation/timeout, 이전 결과와 retry 의도는 호출자가 선언한다. REQUIRED 참여 시 요청 timeout이 새로 적용되지 않을 수 있고 REQUIRES_NEW는 독립 commit될 수 있다. JPA NESTED는 JDBC savepoint와 영속성 컨텍스트를 함께 복구한다고 보장할 수 없어 차단한다.
- timeout은 holder의 hasTimeout/getDeadline만 읽어 UNKNOWN/NONE/ACTIVE/EXPIRED로 분류한다. getTimeToLive 조회로 rollback-only를 변경하지 않는다. rollback은 해당 Spring holder만 반영하며 provider-local/JPA 전역 상태의 완전한 판정이 아니다.
- 불명 commit 결과는 `OUTCOME_UNKNOWN_NO_RETRY` ERROR다. timeout·불명 결과의 자동 재시도나 서버 실행 중 쿼리의 즉시 취소를 수행하지 않는다. SQL·flush·캐시·트랜잭션 설정과 수명을 변경하지 않는다.

## 검증과 재현

```bash
python3 tools/run-phase4.py
python3 tools/verify-phase4.py
```

| 검증 항목 | 실제 실행 결과 |
| --- | --- |
| JDK 전용 Guard 정책 | 123 assertions PASS |
| Spring 연결·스레드 진단 | 52 assertions PASS |
| 신규 트랜잭션 계약 | 205 assertions PASS (실제 Spring/H2 9개 시나리오, 불명 결과 정책 1개) |
| 기존 혼용 H2 회귀 | 10개 시나리오 PASS |
| 기존 Core·Observe·어댑터 회귀 | 74 / 202 / 188 assertions PASS |
| 증거 검증기 | 13개 검사 PASS (경로 삽입·누락 등 부정 사례 포함) |

실행·검증기·최종 판정 증거. [PHASE4-VALIDATION.json](../../evidence/PHASE4-VALIDATION.json), [PHASE4-VERIFIER-VALIDATION.json](../../evidence/PHASE4-VERIFIER-VALIDATION.json), [PHASE4-GATE.json](../../evidence/PHASE4-GATE.json).

첫 실행에서 Spring 진단 49 assertions가 통과했다. 이후 독립 정적 검토에서 비치명 `AssertionError` 원문 전파, 이전 증거의 허용 경로 목록 누락, 소스 해시 전 금지 경로 검사 누락과 의존성 항목별 증거 검증 누락을 확인했다. 해당 경계를 보강한 뒤 최종 보호 실행과 검증기가 PASS했다. 이전 성공 실행 증거는 `.git/udak-phase4/previous-reports`에 보존했다.

새 기능의 실제 검증 범위는 Spring/H2의 로컬 전파·정책 경계다. 네 벤더의 신규 readOnly/isolation/timeout 매트릭스, XA/분산 원자성, Boot 자동 구성·Gradle·Boot 3/4 인증, 운영 복구 및 부하/성능은 NOT RUN으로 관리한다. 기존 Phase 3의 4종 실DB 40개 증거를 별도 보존하며 Phase 4에서 재실행했다고 표시하지 않는다.

실행기는 기존 Phase 3 고정 의존성 36개를 재사용하고 Java 17 대상, JVM heap 256 MiB·metaspace 128 MiB·활성 CPU 2, 자식 CPU 30초·전체 300초 및 작업 공간 2,000개/128 MiB 상한을 적용한다. 성공·실패·정상 중단에 소유 작업 공간 자동 정리를 연결한다. 원본·불명 자료·기존 관리형 DB 8개·데이터·비밀 설정은 보존한다.

최종 보호 실행은 임시 작업 공간의 파일 152개(38,113,156바이트)를 자동으로 회수했고 잔여 파일과 작업 공간은 0개였다. 신규 Docker 컨테이너 기동은 0개다. 기존 관리형 DB 8개는 정지 상태로 데이터와 함께 보존했다.

## 근거와 다음 단계

Spring 6.2.19의 [전파 처리](https://github.com/spring-projects/spring-framework/blob/v6.2.19/spring-tx/src/main/java/org/springframework/transaction/support/AbstractPlatformTransactionManager.java), [JPA 트랜잭션 경계](https://github.com/spring-projects/spring-framework/blob/v6.2.19/spring-orm/src/main/java/org/springframework/orm/jpa/JpaTransactionManager.java), [MyBatis-Spring 트랜잭션 계약](https://mybatis.org/spring/transactions.html)을 기준으로 구현한다.

다음 개발 대상은 Phase 5 검증·승인 SQL 선택 변환이다. Query ID·정확 SQL fingerprint·환경/스키마/provider 버전·검증 evidence를 함께 확인하고, 미승인·미지원·불일치를 기본 차단한다. 실제 의미 동등성 검증 없이 자동 변환을 활성화하지 않는다.
