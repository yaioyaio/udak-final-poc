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

## Observe 관측 공백 진단

- **SQL 실행 성공과 정규화 불가.** `InventoryIntegrationTest`와 `compare_gap`의 H2 메타데이터 조회 사례에서 조회 성공, `JDBC_EXECUTE` 이벤트 1건, `UNSUPPORTED_SYNTAX` 사유의 관측 불가 1건, 정규화된 shape 없음, 수집 누락 0건을 확인했다. 인벤토리 비교는 `INCOMPLETE`(종료 코드 2)로 표시된다. 결과는 별도의 단언으로 확인한 뒤 대상 DB와 방언에서 작은 합성 테스트 사례로 정규화 사유를 재현한다.
- **MyBatis 로컬 캐시 적중.** `LegacyCompatibilityTest.verifyMyBatisCache`는 한 세션과 트랜잭션에서 `MYBATIS_PREPARE` 건수 증가분 `[1, 0, 1, 0, 1]`을 단언했다. 첫 조회에서 statement를 준비한다. JDBC 갱신 직후와 JPA flush 직후 조회는 로컬 캐시에 적중한다. 각 명시적 캐시 비우기 직후의 조회는 statement를 다시 준비하고 현재 값을 읽는다. 각 조회 결과를 별도로 검증한다. 비교에 같은 세션, 트랜잭션, 로컬 캐시 모드가 사용됐는지 확인한다. 캐시 비우기는 격리된 테스트에서만 수행한다. 캐시 미적중을 확인한 뒤에도 관측이 없으면 interceptor 등록, 수집 범위, 누락 건수를 점검한다.

업무 결과, 이벤트 건수, 설정한 수집 범위를 각각 기록한다. DB까지 도달한 경로의 SQL 실행 성공은 조회 결과 단언으로 확인한다. 빈 수집 결과나 이벤트 부재만으로는 원인을 확정할 수 없다. 보호 실행에서 고정 H2 예제 두 가지가 통과했다. [관측 사례 검증](../../evidence/OBSERVE-COVERAGE-EXAMPLES-VALIDATION.json)

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

운영 레거시 도입 상태 **NOT RUN**. 승인된 프로젝트와 테스트 환경에서 업무 흐름 한 곳, 허용된 테스트 범위, 참여 프레임워크와 예상 대조군을 정한다. OFF와 ON의 업무 동작과 관측 범위를 비교한다. 유지보수 담당자가 각 후보를 예상 변경 또는 관측 공백과 대조한다.

조치할 수 있는 발견, 오탐, 설정 비용을 기록한다. 합성 사례 이름, enum 코드, 건수, 검토한 전체 건수, 구성과 검증에 소요된 시간을 사용한다. 변경한 구성 책임과 확인 범위가 불완전했던 부분을 기록한다. SQL 원문, 입력과 결과 데이터, 로컬 경로, 원본 식별자, 계정, 자격 증명과 로그는 공유 증거에서 제외한다. 검토 결과를 바탕으로 적용 범위 확대 여부를 판단한다.

### T-001 동일 담당자 비교 검토

대상 팀이 유지보수 담당자 한 명, 현재 사용하는 검토 절차와 도구, 격리 시험 환경과 시간대를 승인한 뒤 시작한다. 팀이 해당 흐름으로 승인하면 T-001-S2를 사용한다. 두 사례는 ThingsBoard PR #14858의 COUNT 쿼리 변경과 UUID 바인딩 값만 바꾼 대조군이다. 시작하기 전에 변경 전후 산출물, PostgreSQL 합성 fixture, 판정 기준표, 등록 회귀 테스트 한 건을 고정한다. 동일 담당자에게 두 절차에서 같은 입력과 사례 별칭 두 개를 제공한다. 진행자는 두 검토 결과를 모두 받을 때까지 정답을 공개하지 않는다. 수행 순서와 사전 지식 또는 첫 검토로 정답을 알게 됐는지 기록한다. 두 절차 사이에 시험 작업 공간을 합의한 시작 상태로 되돌린다. [T-001 업무 시나리오](15-MARKET-VS-EXISTING.md#t-001-고객-업무-시나리오)

설정 시간은 합의한 시작 상태부터 담당자가 두 사례를 검토할 준비를 마칠 때까지다. 검토 시간은 첫 사례를 열 때부터 두 사례의 판정과 회귀 테스트 선택을 제출할 때까지다. 두 절차에 같은 시작·종료 기준을 적용하고 초 단위로 기록한다. 각 사례는 `changed`(변경), `unchanged`(변경 없음), `unknown`(미확인)으로 판정한다. COUNT 변경을 `changed`로 판정하면 실제 발견(TP) 1건, UUID 대조군을 `changed`로 판정하면 오탐(FP) 1건, COUNT 변경을 `unchanged`로 판정하면 미검출(FN) 1건이다. 판정하지 못했거나 검토하지 않은 사례는 미확인으로 세고 관측 범위의 공백을 기록한다. 선택한 테스트가 등록된 회귀 테스트와 일치하는지 기록한다.

| 기록 항목 | 기존 절차 | UDAK Observe 및 보고서 |
| --- | --- | --- |
| 수행 순서와 사전 지식 또는 앞선 검토의 영향 | ___ | ___ |
| 설정 시간 / 검토 시간(초) | ___ / ___ | ___ / ___ |
| 두 사례 별칭별 판정 | ___ / ___ | ___ / ___ |
| 검토 건수 / 전체, TP / FP / FN / 미확인, 검토 범위 공백 | ___ / 2, ___ / ___ / ___ / ___, ___ | ___ / 2, ___ / ___ / ___ / ___, ___ |
| 선택한 테스트 별칭, 등록 회귀 테스트와 일치 여부 | ___ | ___ |
| 정제된 실행 기록 ID | ___ | ___ |

동일한 승인 담당자가 실제 작성한 절차별 실행 기록 두 건을 모두 확보한 경우에만 비교를 완료한다. 누락 항목은 빈칸으로 두고 미완료 비교는 NOT RUN으로 기록한다. 관찰한 차이는 해당 담당자와 검토 흐름에서 얻은 값으로 보고한다. 기존 ThingsBoard 기록의 역할은 자기 선언이고, 기존 시간 기록은 UDAK 절차만 계측했다. [기존 시간 기록](../../evidence/THINGSBOARD-NEXT-005-MAINTAINER-REVIEW.json)

2026-11-26 로컬 대행 실행에서 사전에 공개한 두 사례를 각각 새 임베디드 H2 fixture로 재현해 Git diff 절차와 UDAK 절차를 비교했다. 두 절차 모두 COUNT 결과 3·2·1을 확인했고, 쿼리 변경 1건, 오탐·미검출·미확인 각 0건, 동일한 등록 회귀 테스트 1건을 기록했다. 공통 준비는 1.157초였다. 절차별 설정·검토 시간은 Git diff 0.176초·0.062초, UDAK 0.227초·0.081초였다. 이 시간은 답을 알고 있는 고정 사례 두 건의 자동화 실행을 계측한 값이다. 고객과 외부 검토자 참여는 없었다. 당시 PostgreSQL 호스트 사전 조건은 미충족이었으며 임베디드 실행과 정리는 통과했다. [로컬 대행 증거](../../evidence/T-001-LOCAL-PAIRED-REVIEW.json)

2026-11-27에는 같은 두 사례를 격리 PostgreSQL 18에서 재현했다. 두 절차는 같은 초기 데이터의 별도 임시 테이블을 사용했다. COUNT 결과 3·2·1, 발견 1건, 오탐·미검출·미확인 각각 0건과 동일한 등록 회귀 테스트 한 건을 확인했다. 공통 준비는 2.691초였고, 설정·검토는 Git diff가 0.181초·0.062초, UDAK가 0.238초·0.079초였다. 계측 범위는 결과를 알고 있는 고정 사례의 로컬 자동화다. 고객 측정은 NOT RUN이다. 컨테이너와 작업 공간 정리를 확인했다. [PostgreSQL 로컬 대행 증거](../../evidence/T-001-LOCAL-PAIRED-REVIEW-POSTGRESQL.json)

같은 날 독립 로컬 검토자 한 명에게 정답을 공개하기 전에 같은 두 사례를 별칭으로 제공했다. 검토자는 Git diff와 보호 UDAK PR 보고서를 순서대로 검토하고 두 기록을 별도로 제출했다. 두 절차 모두 발견 1건, 오탐·미검출·미확인 각 0건, 등록 재현 테스트 1건을 기록했다. 관측 데이터는 임베디드 H2에서 새로 수집했고 격리 PostgreSQL의 앞선 기술 증거와 연결했다. 로컬 에이전트의 설정·검토 경과 시간은 Git diff 7.661초·12.150초, UDAK 0.026초·11.539초였다. 첫 절차에서 검토 목록을 처음 확인했고 두 번째에는 같은 사례를 이미 검토한 영향을 기록했다. 승인된 고객 담당자의 비교와 시간 측정은 NOT RUN이다. [로컬 검토자 기록](../../evidence/T-001-LOCAL-OPERATOR-PAIRED-REVIEW.json)

### T-001 로컬 비교 결론

2026-11-28 저장된 두 자동 대행과 독립 검토 결과를 현재 소스에 대조했다. 세 기록의 입력 해시 21개씩과 판정, 등록 테스트, 정리 결과가 일치했다. SQL 인벤토리 회귀 39건과 Core 스모크를 통과했다. 별도 장치 DAO PR #14036은 보존 지문으로 보호 PR 보고서의 변경·대조군 JSON과 변경 Markdown을 재생성했다. 세 파일의 SHA-256이 기존 실DB 실행 기록과 일치했고 임시 파일을 정리했다. 이번 검증에서 DB를 기동하지 않았다. [PostgreSQL 비교 기록](../../evidence/T-001-LOCAL-PAIRED-REVIEW-POSTGRESQL.json) · [독립 로컬 검토](../../evidence/T-001-LOCAL-OPERATOR-PAIRED-REVIEW.json) · [장치 DAO 증거](../../evidence/THINGSBOARD-DEVICE-DAO-FOLLOWUP-VALIDATION.json)

| 질문 | 확인된 결과 |
| --- | --- |
| 발견과 오탐이 달라졌는가 | 두 절차 모두 COUNT 변경 1건, UUID 대조군 오탐 0건, 미검출·미확인 각 0건으로 같았다. |
| UDAK가 추가로 제공하는 것은 무엇인가 | SQL 지문 변경, 영향받는 쿼리와 등록 회귀 테스트를 한 보고서에서 연결한다. Git diff 비교에서는 별도 테스트 등록 정보를 참조해 같은 테스트 한 건을 골랐다. |
| 검토 시간이 줄었는가 | 이미 답을 아는 PostgreSQL 자동 비교에서 공통 준비를 제외한 설정·검토 합계는 Git diff 0.243초, UDAK 0.317초였다. 독립 로컬 검토의 두 번째 절차에는 먼저 본 사례의 영향이 있었다. 고객 시간 절감은 미확인이다. |

**T-001 로컬 대행 검증은 완료(PASS)**다. 승인된 유지보수팀의 담당자가 두 절차를 수행해야 하는 고객 직접 비교는 이번 로컬 범위에서 종료하며 **NOT RUN**으로 남긴다. 고객 수요와 도입 효과는 미확인이다. 승인된 팀이 확보되면 기존 절차와 UDAK를 업무 흐름 하나에서 비교한다. 그 결과에서 확인된 관측 공백이나 검토 불편만 다음 기능 개선 대상으로 삼는다.

#### 별도 공개 PR 독립 검토

2026-11-28 ThingsBoard PR #14036의 실제 반환 열 변경과 값만 바꾼 합성 대조군을 로컬 검토 에이전트 두 명이 독립적으로 검토했다. 한 명은 고정 공개 소스에서 추출한 변경 diff를, 다른 한 명은 보호 PR 보고서를 받았다. 같은 테스트 카탈로그를 제공했고 정답과 상대 절차는 제출 전에 공개하지 않았다. 첫 실행은 판정 차이를 실패로 처리한 집계 오류 때문에 시간 기록을 잃었다. 판정 차이를 그대로 기록하도록 고친 뒤 같은 자료로 새 검토자 두 명이 한 번 검토했다. [독립 검토 증거](../../evidence/T-001-INDEPENDENT-DEVICE-PR-REVIEW.json)

| 방식 | 실제 발견 | 오탐 | 미검출 | 미확인 | 등록 테스트 선택 | 검토 시간 |
| --- | ---: | ---: | ---: | ---: | --- | ---: |
| Git diff | 1 | 0 | 0 | 1 | 일치 | 7.095초 |
| UDAK 보고서 | 1 | 0 | 0 | 0 | 일치 | 6.308초 |

Git diff 검토자는 입력값만 달라진 대조군의 SQL 형태가 같은지 판단할 관측 근거가 부족하다고 기록했다. UDAK는 대조군에서 관측된 지문이 같음을 보여 줬고, 실제 변경에만 영향 테스트 해시를 제시했다. 시간은 자료를 연 뒤 제출까지의 에이전트 경과이며, 공통 준비를 제외한다. 방식별 검토자가 한 명이므로 고객 시간 절감은 미확인이다. 승인된 팀의 직접 비교는 **NOT RUN**으로 남긴다.

UDAK 검토에서 남은 수작업은 해시 대조였다. 검토 시 보호 보고서의 `impacted_test_ids`를 같은 자료의 등록 테스트 참조와 맞춰 실제 실행할 항목을 확인한다. 이 파일럿은 장치 DAO 검증 기록의 `test_id_hash`를 사용한다. 일치하는 항목이 없으면 미확인으로 기록한다. 이번 변경은 그 절차를 문서에 추가했다. [장치 DAO의 등록 테스트 근거](../../evidence/THINGSBOARD-DEVICE-DAO-FOLLOWUP-VALIDATION.json)

### ThingsBoard CE 외부 파일럿

NEXT-005의 외부 검증 대상은 ThingsBoard CE `v4.3.1.8`의 `ebbfc6789b81a4e04cae2711208130fb2841b31f` 커밋이다. UDAK와 별도인 `thingsboard-ce-v4.3.1.8` 폴더에 detached HEAD로 고정한다. 공개 소스를 받을 때 환경·키 파일 45개를 제외했다. 체크아웃은 깨끗하고 제외한 Git blob도 로컬에 없다. [상류 릴리스](https://github.com/thingsboard/thingsboard/releases/tag/v4.3.1.8)

고정 업무 흐름은 `dao`의 장치 등록이다. `DeviceServiceTest#testFindDeviceById`에서 저장·조회 결과를 대조하고 `DeviceServiceTest#testShouldRollbackValidatedDeviceIfDeviceCredentialsValidationFailed`에서 실패한 등록의 DB 잔존 여부를 확인한다. 게시 JAR 실행은 Surefire 테스트 목표에서 정확한 두 메서드를 지정하고 JVM fork 하나를 사용한다. 기존 PostgreSQL 초기화는 테스트 스키마를 재구성하므로 전용 DB를 사용한다. 두 메서드의 Surefire 결과에서 실행 및 실패·오류·건너뜀 0건을 확인한 뒤 기준선을 확정한다. [등록 성공 테스트](https://github.com/thingsboard/thingsboard/blob/v4.3.1.8/dao/src/test/java/org/thingsboard/server/dao/service/DeviceServiceTest.java#L610) · [롤백 테스트](https://github.com/thingsboard/thingsboard/blob/v4.3.1.8/dao/src/test/java/org/thingsboard/server/dao/service/DeviceServiceTest.java#L216) · [PostgreSQL 초기화](https://github.com/thingsboard/thingsboard/blob/v4.3.1.8/dao/src/test/java/org/thingsboard/server/dao/PostgreSqlInitializer.java#L18-L49)

기준선 통과 후 주 `entityManagerFactory`에 테스트 전용 설정으로 UDAK Hibernate inspector를 연결한다. 합성 가능한 기존 inspector는 보존한다. 같은 업무 코드와 테스트 본문에서 Observe OFF/ON의 업무 단언, 지문 관측 범위, 연결에 든 시간을 비교한다. 업무 호환성을 확인한 뒤 검토된 상류 SQL 변경 검출을 별도로 검증한다.

ThingsBoard 공식 Maven 저장소에서 게시 `langchain4j-bom:1.16.1-TB1`, 부모 POM, `langchain4j`와 `langchain4j-core`의 POM·JAR을 확보했다. 6개 파일 모두 공급자 SHA-256과 일치했고 두 JAR의 내부 메타데이터에서 좌표를 확인했다. 아티팩트는 외부 파일럿 전용 Maven 저장소에 보존한다. 앞선 의존성 진단은 이력으로 보존한다. [공식 게시본 검증](../../evidence/THINGSBOARD-TB1-OFFICIAL-ARTIFACTS.json) · [이전 의존성 진단](../../evidence/THINGSBOARD-DEVICE-PILOT-DEPENDENCIES.json)

공식 게시 DAO 테스트 JAR과 게시 의존성을 공급자 체크섬으로 검증했다. DAO POM과 시험 설정 파일 두 개가 고정 소스와 일치했다. PostgreSQL 18에서 두 차례 실행했고 Surefire는 각각 테스트 2건, 실패·오류·건너뜀 각 0건을 기록했다. 교차 확인 실행에서 새 PostgreSQL 시험 컨테이너 1개를 관측했다. 종료 후 프로세스, 임시 작업 폴더, 추가 시험 컨테이너와 볼륨이 정리됐다. 호스트는 검증된 로컬 PostgreSQL 18.7 이미지를 요구된 메이저 버전 태그로 사용했다. [기준선 결과](../../evidence/THINGSBOARD-DEVICE-BASELINE-VALIDATION.json) · [이전 소스 빌드 진단](../../evidence/THINGSBOARD-DAO-REACTOR-VALIDATION.json)

별도의 PostgreSQL 18 시험 인스턴스에서 공식 게시 메서드 두 건이 Observe OFF와 ON 모두 통과했다. OFF에서 이벤트는 0건이었다. ON은 Hibernate 관측기를 한 곳에 연결했고 등록·조회에서 이벤트 17건(지문 16개), 롤백에서 이벤트 7건(지문 7개)을 수집했다. 두 테스트에서 수집 누락과 관측 불가는 각각 0건이었다. 관측은 테스트 메서드 본문의 동기 호출 범위로 한정했다. [Observe 비교](../../evidence/THINGSBOARD-OBSERVE-AND-SQL-CHANGE-VALIDATION.json)

ThingsBoard PR #14858의 변경 전·후 소스 blob을 검증했다. 합성 테넌트 두 개를 넣은 일회용 PostgreSQL 18 테이블에서 원래 COUNT SQL 두 문장과 UUID 값만 바꾼 대조군을 UDAK JDBC 관측을 거쳐 실행했다. 보고서는 같은 논리 쿼리에서 이전 지문 1건 제거, 새 지문 1건 추가, 영향 재현 테스트 1건을 표시했고 UUID 대조군 변경은 0건이었다. 재현 범위는 고정한 SQL 문장과 격리 시험 데이터다. 역사 버전 전체 애플리케이션 실행과 운영 적용은 NOT RUN이다. [상류 PR](https://github.com/thingsboard/thingsboard/pull/14858) · [SQL 재현 증거](../../evidence/THINGSBOARD-OBSERVE-AND-SQL-CHANGE-VALIDATION.json)

### ThingsBoard 도입 검토

독립 기술 검토에서 조치할 수 있는 COUNT 변경 1건과 UUID 값 대조군의 오탐 0건을 확인했다. 재현 코드가 인벤토리 범위를 명시해 영향 테스트 해시를 연결한다. 검증된 캐시를 사용한 로컬 리허설에서 아티팩트 확인, Observe 코드 재빌드와 시험 폴더 설정에 1.229초가 걸렸다. 원본·기존 증거 검토와 인벤토리 회귀 28건에는 1.048초가 걸렸다. 자원 점검이 통과한 뒤 PostgreSQL 재현, 보고서 검증과 정리에 3.011초가 걸렸다. 변경 전·후 인벤토리의 지문별 시험 해시가 보고서의 영향 테스트 해시와 일치했다. [기술 검토 리허설 증거](../../evidence/THINGSBOARD-NEXT-005-ADOPTION-REVIEW.json)

2026-11-24 담당자 직접 검토는 PASS다. 검증된 캐시에서 설정에 16.368초, 결과 검토와 확인 입력을 포함한 검증에 45.044초가 걸렸다. 재개 시 기존 설정 시간을 보존했다. PostgreSQL 단언 3건, 인벤토리 회귀와 정리를 통과했다. 확인한 변경은 1건, UUID 값 대조군 변경은 0건이었다. 수행자가 `thingsboard-maintainer` 역할을 직접 선언했다. 외부 신원 확인은 미실시다. [직접 검토 증거](../../evidence/THINGSBOARD-NEXT-005-MAINTAINER-REVIEW.json)

### 장치 DAO의 두 번째 SQL 변경

ThingsBoard PR #14036의 병합 직전·직후 리비전과 `DefaultNativeDeviceRepository.java`의 파일 해시를 고정했다. `findProfileEntityIdInfosByTenantId`의 고객 ID 반환 컬럼 추가를 동일 관측 프로파일의 격리 PostgreSQL 18에서 검증했다. 변경 전후의 장치·테넌트·프로파일 값과 페이지 결과는 일치했고, 변경 후 고객 ID가 추가됐다. 테넌트 UUID만 바꾼 대조군은 다른 장치를 반환하고 같은 SQL 지문으로 관측됐다. [ThingsBoard PR #14036](https://github.com/thingsboard/thingsboard/pull/14036)

보호 실행기 `python3 -B tools/thingsboard-pilot/replay-upstream-device-profile.py`에서 PostgreSQL 결과 단언 3건을 통과했다. 리포트 두 건은 COMPLETE였다. SQL 변경 보고서는 추가·제거 지문 한 건씩과 등록된 재현 테스트 한 건을 표시했다. 영향 테스트 해시는 변경 전후 인벤토리의 지문별 테스트 해시와 일치했다. UUID 대조군의 변경과 영향 테스트는 0건이었다. 시험 컨테이너와 임시 폴더 정리도 통과했다. 검증 범위는 고정 SQL과 격리 fixture다. 역사 버전 앱 실행, Java 소유자 매핑 및 운영 적용은 NOT RUN이다. [추가 SQL 재현 증거](../../evidence/THINGSBOARD-DEVICE-DAO-FOLLOWUP-VALIDATION.json)

### 담당자 직접 시간 측정

파일럿 맥에서 검증된 ThingsBoard 캐시와 로컬 시험 폴더, JDK 21, 고정된 PostgreSQL 이미지를 사용한다. UDAK 루트에서 담당자 본인의 터미널로 실행하고 실제 역할을 선택한다.

```bash
python3 -B tools/thingsboard-pilot/run-maintainer-review.py --role thingsboard-maintainer
```

UDAK 유지보수 담당자는 `--role udak-maintainer`를 사용해 자신의 검토 범위를 기록한다. 설정 시간은 첫 Enter 후 자원 점검을 통과할 때부터 원본 테스트 보존과 정리를 확인해 `CONFIRM`을 입력할 때까지다. 검증 시간은 두 번째 Enter 후 자원 점검을 통과할 때부터 SQL 변경과 UUID 대조군의 결과를 검토하고 두 건수를 입력할 때까지다. 도구는 고정 COUNT 재현, 인벤토리와 영향 테스트 해시 대조, 인벤토리 회귀 시험, 컨테이너 및 작업 폴더 정리를 확인한다. 중단된 세션은 미완료로 기록한다. [재현 및 검토 범위](#thingsboard-도입-검토)

아티팩트 확인과 관측기 설정은 macOS 메모리 압력 1·2단계에서 스왑 여유가 768 MiB 이상이면 시작할 수 있다. 설정 시작 입력 후 이 조건을 충족할 때까지 최대 60초 기다린 뒤 계측을 시작한다. 시간이 초과되면 `SETUP_HOST_PREFLIGHT`와 측정한 압력 단계, 스왑 여유를 기록한다. PostgreSQL 검증은 메모리 압력 1단계와 같은 스왑 여유를 요구한다. 설정을 확인하면 시간을 저장한다. PostgreSQL 검증이 대기 상태면 출력된 `--resume RECEIPT_NAME` 명령을 같은 역할로 실행한다.

PostgreSQL 출력에서 `changed_queries`가 1이고 `uuid_only_changes`가 0인지 확인한다. 마지막 입력란에 `1 0`을 입력하고 Enter를 누른다. 빈 입력이나 다른 값은 같은 입력란에서 다시 받는다. 이때 PostgreSQL 검증은 다시 실행되지 않는다.

도구는 파일럿 폴더에 메타데이터만 포함한 `NEXT-005-MAINTAINER-*.json` 기록을 만들고 파일명을 표시한다. 담당자의 역할, 두 구간 시간, 직접 검토 확인이 있는 PASS 기록을 제출한다. 역할은 수행자가 직접 선언한다. `--rehearsal` 모드는 절차 검증용 리허설 기록을 생성한다. [시간 측정 도구](../../tools/thingsboard-pilot/run-maintainer-review.py)
