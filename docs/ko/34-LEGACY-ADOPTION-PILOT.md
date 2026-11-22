# 레거시 Observe 도입 시범 적용

[English](../en/34-LEGACY-ADOPTION-PILOT.md) | 한국어

NEXT-005 / FR-005 / FR-006 / FR-007 / FR-008 / NFR-03. Hibernate·MyBatis·JdbcTemplate이 DataSource를 공유하는 기존 애플리케이션에서 테스트 가능한 경로 한 곳부터 시작한다. Observe는 Java 구성에 명시적으로 연결한다. 참조 구성은 Hibernate 6.6.53.Final, Spring Framework 6.2.19, MyBatis 3.5.19, MyBatis-Spring 3.0.5, H2 2.3.232를 사용한다. [추적성](16-TRACEABILITY.md) · [Phase 3 결과와 버전 범위](21-LEGACY-OBSERVE-RESULTS.md)

## 기존 애플리케이션에 Observe 연결

저장소의 `legacy-observe`와 `sql-inventory` 모듈을 사용한다. 팩토리 생성과 초기화 전에 OFF 또는 ON을 선택한다. OFF에서는 원본 DataSource와 기존 Hibernate inspector를 사용한다. ON에서는 wrapper를 한 번 만들고 JPA 팩토리와 로컬 트랜잭션 매니저, MyBatis 팩토리, JdbcTemplate에 같은 참조를 전달한다. 원본 DataSource와 커넥션 풀은 애플리케이션이 계속 관리한다.

```java
var capture = new InventoryCapture();
var observer = new SqlObserver(capture);
DataSource shared = observeEnabled ? new ObserveDataSource(originalDataSource, observer)
        : originalDataSource;

jpaFactory.setDataSource(shared);
StatementInspector inspector = existingInspector;
if (observeEnabled) {
    inspector = existingInspector == null ? new HibernateObserveInspector(observer)
            : HibernateObserveInspector.compose(existingInspector, observer);
}
if (inspector != null) {
    jpaFactory.getJpaPropertyMap().put("hibernate.session_factory.statement_inspector", inspector);
}

if (observeEnabled) {
    myBatisConfiguration.addInterceptor(new MyBatisObserveInterceptor(observer));
}
myBatisFactory.setDataSource(shared);
myBatisFactory.setConfiguration(myBatisConfiguration);
myBatisFactory.setTransactionFactory(new SpringManagedTransactionFactory());

var jdbc = new JdbcTemplate(shared);
// After initializing the existing JPA factory:
var transactionManager = new JpaTransactionManager(entityManagerFactory);
transactionManager.setDataSource(shared);
```

`jpaFactory`와 `myBatisFactory`는 기존 `LocalContainerEntityManagerFactoryBean`과 `SqlSessionFactoryBean`이다. `existingInspector`에는 기존 inspector 인스턴스 또는 `null`을 넘긴다. 애플리케이션의 기존 팩토리 수명주기와 `SqlSessionTemplate`, 로컬 트랜잭션 매니저 구성을 사용한다. ON 구성에서 interceptor는 한 번 등록한다. Hibernate 합성기는 기존 inspector의 반환값과 예외 동작을 보존하고 실행에 사용되는 SQL을 관측한다. [참조 통합 테스트](../../legacy-compat-testkit/src/test/java/dev/udak/compat/LegacyCompatibilityTest.java#L283)

OFF와 ON에서 같은 업무 결과와 롤백을 비교한다. 기존 flush·캐시·트랜잭션 경계를 유지한다. 다른 접근 경로에서 보류 중인 JPA 쓰기를 읽어야 한다면 기존의 명시적 flush 지점을 검사한다. 캐시의 오래된 값과 명시적 refresh 또는 clear는 별도로 검증한다. 검증된 트랜잭션 계약 범위는 공유 로컬 DataSource다. [Observe 계약과 한계](21-LEGACY-OBSERVE-RESULTS.md) · [로컬 트랜잭션 진단](22-TRANSACTION-GUARD-RESULTS.md)

## 정제된 진단 수집

실행별로 별도의 `InventoryCapture`를 사용한다. 같은 스레드에서 수행하는 테스트 동작은 `capture.scope("MYBATIS_USER_LOOKUP", "LOOKUP_CASE")`와 같은 try-with-resources 범위로 묶는다. 비교 실행에서 같은 합성 ID를 사용한다. 관측이 끝난 뒤 `snapshotJson(revision, profile)`을 호출한다. 리비전은 40자 또는 64자 소문자 16진수, 프로파일은 64자 소문자 16진수 해시를 전달한다. 서로 동등한 프로파일을 인벤토리 보고서로 비교한다. 차이를 해석하기 전에 누락된 관측 건수를 확인한다. [인벤토리 사용법과 보고서](25-SQL-INVENTORY-PR-REPORT.md)

사용자 정의 sink는 `ObservationSink`의 두 메서드를 구현하고 `accept(SqlObservation, UnavailableReason)`에서 사유를 받는다. 인수 하나를 받는 sink에는 관측 이벤트만 전달된다. 사유는 렉서의 최초 거부를 나타낸다. `NONE`은 shape 정규화 성공, `UNSPECIFIED`는 관측 불가 이벤트에 구체적 사유가 없음을 의미한다. `UNSUPPORTED_SYNTAX`, `AMBIGUOUS_SYNTAX`, `SQL_TOO_LONG` 같은 코드는 정규화 범위를 나타낸다. 빠르고 스레드 안전한 sink에서 프레임워크·관측 지점·사유별 집계를 제한된 범위로 남긴다. SQL 원문, 바인드 값과 리터럴, 원본 ID, 경로, 접속·계정 정보, 비밀값과 예외 원문은 기록에서 제외한다. [고정 사유 코드](../../observe-core/src/main/java/dev/udak/observe/UnavailableReason.java) · [사유 계약 테스트](../../observe-core/src/test/java/dev/udak/observe/ObserveContractTest.java#L80)

`JPA_INSPECT`, `MYBATIS_PREPARE`, `JDBC_EXECUTE`는 각 지점에 도달한 관측 건수다. 한 작업이 여러 지점에 관측될 수 있으며 MyBatis는 캐시 히트에서 prepare를 건너뛸 수 있다. SQL 성공 여부는 업무 결과 단언으로 확인한다. shape 지문은 인벤토리 분류에 쓰이며 다른 SQL 형태에서 같은 지문이 나올 수 있다. 변환 결정에는 별도의 정확 SQL 지문과 승인 절차를 사용한다. [레거시 호환과 승인 변환](05-LEGACY-COMPATIBILITY.md)

## 기존 H2 통합 환경에서 리허설

```bash
python3 -B tools/run-legacy-adoption.py
```

비교 전에 검토 후보 두 건을 정한다. MyBatis 사례 한 건은 동일 논리 ID에서 SQL shape가 달라지고 JDBC 사례 한 건은 관측 범위에 새로 추가된다. 독립 대조군은 바인드 값만 바뀌므로 검토 후보가 없어야 한다. SQL은 성공하지만 정규화가 지원되지 않는 별도 사례는 정제된 관측 불가 사유를 보고해야 한다. 실제 후보와 예상 후보 집합을 대조하고 이 고정 사례에서 예상 밖 후보를 센다. 구성 책임별로 설정 지점(공유 DataSource, Hibernate, MyBatis, JDBC 연결)을 기록하고 수동 설정 시간은 미측정으로 남긴다. 고정된 조건에서 예상 사례를 구분할 수 있는지 확인한다.

내부 리허설은 예상 검토 후보 2건을 모두 찾았으며 변경 없는 인벤토리 항목 5개에서 오탐 0건이었다. 별도의 H2 메타데이터 조회는 성공했고 `UNSUPPORTED_SYNTAX` 1건이 집계되어 해당 비교는 `INCOMPLETE`로 표시됐다. 연동 설정 지점 3곳과 Observe OFF/ON에서 동일한 데모 소스 사용을 검증했다. 레거시 10건, inspector 4건, 시범 인벤토리 28건, 기존 수집 14건 및 보호 Core 스모크가 통과했다. 운영자 수동 설정 시간은 미측정이며 인메모리 H2만 실행했다. [H2 메타데이터 명령 참조](https://h2database.github.io/html/commands.html#show) · [리허설 증거](../../evidence/LEGACY-ADOPTION-VALIDATION.json)

## 독립 주문 서비스 파일럿

사용자는 빈 저장소를 주문 파일럿 대상으로 지정했다. Spring 애플리케이션 기준선을 먼저 만든 뒤 별도 테스트 소스에 Observe를 연결했다. JPA 주문 저장과 flush, MyBatis 재고 예약, JdbcTemplate 감사 기록은 동일 DataSource와 로컬 트랜잭션을 공유한다. 바이트가 동일한 기준선의 단언 25개와 Observe 파일럿의 단언 107개가 통과했다. OFF와 ON에서 정상 응답과 저장 결과가 같았고 세 쓰기 후 실패 시 주문·재고·감사가 모두 원복됐다.

보고서는 활성 재고 조건이 추가된 SQL 변경을 검토 후보 한 건으로 식별했다. MyBatis와 JDBC가 각각 관측했다. 바인딩 값만 바꾼 대조군은 인벤토리 항목 3개에서 오탐 0건이었다. 성공한 H2 메타데이터 조회는 `UNSUPPORTED_SYNTAX` 1건으로 집계되어 관측 범위가 `INCOMPLETE`로 표시됐다. 첫 ON의 설정 지점 3곳 연결과 팩토리 초기화는 20.411 ms가 걸렸다. 유지보수 담당자의 수동 설정 시간은 미측정이다. 기존 운영 레거시 적용과 외부 DB 검증은 NOT RUN이다. [독립 파일럿 증거](../../evidence/ORDER-ADOPTION-PILOT-VALIDATION.json)

## 승인된 레거시 프로젝트에 적용

외부 시범 적용 상태 **NOT RUN**. 승인된 프로젝트와 테스트 환경에서 업무 흐름 한 곳, 허용된 테스트 범위, 참여 프레임워크와 예상 대조군을 정한다. OFF와 ON의 업무 동작과 관측 범위를 비교한다. 유지보수 담당자가 각 후보를 예상 변경 또는 관측 공백과 대조한다.

조치할 수 있는 발견, 오탐, 설정 비용을 기록한다. 합성 사례 이름, enum 코드, 건수, 검토한 전체 건수, 구성과 검증에 소요된 시간을 사용한다. 변경한 구성 책임과 확인 범위가 불완전했던 부분을 기록한다. SQL 원문, 입력과 결과 데이터, 로컬 경로, 원본 식별자, 계정, 자격 증명과 로그는 공유 증거에서 제외한다. 검토 결과를 바탕으로 적용 범위 확대 여부를 판단한다.
