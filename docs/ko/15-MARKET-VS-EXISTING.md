# Market fit / Existing Libraries / Buy vs Build

[English](../en/15-MARKET-VS-EXISTING.md) | 한국어

## 제품 차별성 검증

| 기존 라이브러리 | 이미 제공하는 기능 | 중복 재구현하지 않을 기능 | UDAK 자체 가치 후보 |
|---|---|---|---|
| Spring Data JPA/Hibernate | JPA Repository/ORM/Dialect | JPA EntityManager/dirty checking | 혼합 기술/DB 구성 진단 |
| MyBatis/MyBatis-Spring | XML Mapper/트랜잭션 통합 | SQL 실행기/Mapper 기능 | Query inventory/호환성 승인 |
| Spring JdbcTemplate | Connection/PreparedStatement 관리 | JDBC 유틸리티 전체 | 중앙 SQL 정책/레거시 진단 |
| jOOQ | Fluent SQL DSL/Dialect/parsing | 전체 SQL DSL 신규 구현 | 제어 평면/legacy evidence |
| MyBatis Dynamic SQL | SQL builder, MyBatis/Spring JDBC rendering | 기본 쿼리 builder | JPA 포함 진단/점진 도입 |
| Flyway/Liquibase | Schema migrations | Schema migration engine | Schema version과 SQL 승인 연동 |

## 수혜자/비수혜자

**핵심:** SI/SM, 다중 DBMS 상용 솔루션, 기존 MyBatis/JPA 혼합 서비스, DB 이행 담당 백엔드팀.

**선택적:** 단일 PostgreSQL+JPA 서비스, CRUD 작은 앱, DBMS 특화 고성능 쿼리 시스템. 기존 기술만으로 충분할 수 있다.

## T-001 고객 업무 시나리오

아래 다섯 건은 공개 프로젝트의 사례와 기존 기술 검증을 바탕으로 정의한 고객 수요 가설이다. 실제 대상 고객 인터뷰, 운영 도입, 구매 의향 확인은 **NOT RUN**이다. [로드맵](09-WBS-ROADMAP.md) · [추적성](16-TRACEABILITY.md)

| ID | 담당자와 계기 | 업무 흐름과 대조군 | 측정 가능한 성공 기준 | 기술 근거와 미검증 범위 |
|---|---|---|---|---|
| T-001-S1 | 레거시 유지보수 담당자가 장치 등록의 회귀 위험을 줄이면서 SQL 관측을 도입한다. | 같은 ThingsBoard 원본 장치 등록·조회 및 실패 시 롤백 테스트를 Observe OFF/ON으로 실행한다. ON에서 테스트 설정 한 곳에 Hibernate 관측기를 연결한다. | 업무 단언은 양쪽에서 두 건 모두 통과한다. OFF 이벤트는 0건, ON은 등록·조회 17건과 롤백 7건을 수집하고 두 테스트 모두 수집 누락과 관측 불가가 0건이다. | 공식 게시 테스트의 동기 호출 범위를 격리 PostgreSQL 18에서 검증했다. 고객 운영 환경과 다른 업무 경로는 미검증이다. [외부 파일럿](34-LEGACY-ADOPTION-PILOT.md#thingsboard-ce-외부-파일럿) · [OFF/ON 실행 증거](../../evidence/THINGSBOARD-OBSERVE-AND-SQL-CHANGE-VALIDATION.json) |
| T-001-S2 | PR 검토자가 장치 수를 세는 SQL 변경과 요청 값 차이를 구분한다. | ThingsBoard PR의 변경 전후 COUNT SQL을 같은 PostgreSQL 시험 데이터로 실행하고 동일 논리 쿼리의 지문을 비교한다. UUID 바인드 값만 바꾼 실행을 대조군으로 둔다. | 변경 보고서에 이전 지문 제거 1건, 새 지문 추가 1건, 영향 재현 테스트 1건이 표시된다. 값 대조군의 변경은 0건이다. | 공개 PR의 고정 SQL과 격리 데이터에서 재현했다. 역사 버전 전체 앱 실행과 고객 PR 검토 성과는 미검증이다. [ThingsBoard PR #14858](https://github.com/thingsboard/thingsboard/pull/14858) · [SQL 재현 증거](../../evidence/THINGSBOARD-OBSERVE-AND-SQL-CHANGE-VALIDATION.json) |
| T-001-S3 | DBA와 QA가 배포 전 관측된 스키마 차이가 장치 조회에 미치는 영향을 확인한다. | 기준·변경 스키마의 JDBC 메타데이터를 비교하고 관측 지문을 검토된 의존성과 연결한다. `device.customer_id` 제거에서 선택한 등록 테스트는 스키마 해시를 대조한 뒤 재실행한다. 미사용 컬럼의 길이 변경을 대조군으로 둔다. | 두 보고서는 `COMPLETE`다. 컬럼 제거에서 테스트 1건이 선정되고 SQLSTATE `42703`을 재현한다. 미사용 컬럼 변경은 0건을 선정하며 조회 결과와 지문이 기준과 일치한다. | 공개 Flyway 이슈는 적용된 기준선 마이그레이션의 체크섬 불일치를 `validate`가 보고하지 않은 사례다. UDAK 근거는 별도의 격리 PostgreSQL 18 장치 조회 한 건이며, 해당 Flyway 이슈의 재현과 고객 스키마 적용은 미검증이다. [Flyway #4106](https://github.com/flyway/flyway/issues/4106) · [장치 스키마 영향 증거](../../evidence/THINGSBOARD-DEVICE-SCHEMA-IMPACT-VALIDATION.json) |
| T-001-S4 | Spring 유지보수 담당자가 주문, 재고, 감사 쓰기를 함께 변경하면서 로컬 트랜잭션 경계를 검토한다. | 공유 DataSource에서 JPA 주문 저장·명시적 flush, MyBatis 재고 예약, JdbcTemplate 감사 기록을 실행한다. 정상 커밋을 세 쓰기 이후 실패 경로와 대조하고, 별도의 추적 테스트로 세 접근 경로의 경계 참여와 flush 전후 가시성을 확인한다. | 정상 경로에서 주문·재고·감사 결과가 모두 반영되고 실패 경로에서 모두 원복된다. 추적 테스트는 세 접근 경로가 같은 로컬 경계에 참여하며 flush 전후 MyBatis 가시성 차이를 확인한다. | 저장 프로시저 호출 전 flush 관련 공개 보고는 경계 검토의 계기다. UDAK는 별도의 Spring/H2 주문 및 추적 fixture를 검증했다. 공개 이슈 재현, 고객 실DB, 프레임워크 전반의 캐시·flush 동작과 분산 트랜잭션은 미검증이다. [Spring Data JPA #3434](https://github.com/spring-projects/spring-data-jpa/issues/3434) · [주문 파일럿](../../evidence/ORDER-ADOPTION-PILOT-VALIDATION.json) · [경계 추적 증거](../../evidence/TX-TRACE-VALIDATION.json) |
| T-001-S5 | 운영 담당자가 중요 쓰기의 JDBC 커밋 응답을 받지 못했을 때 중복 처리를 막는다. | 격리 PostgreSQL과 MySQL에서 커밋 응답 유실을 검증한다. 클라이언트에서 결과를 확정할 수 없으면 `TransactionGuard`의 차단 판정을 확인하고 별도 연결로 실제 커밋을 대조한다. | 두 DB에서 JDBC 커밋 호출은 실패하고 자동 재시도는 차단된다. 독립 조회로 해당 쓰기가 정확히 한 번 반영됐음을 확인한다. | 공개 pgjdbc 이슈는 서버 연결 종료 후 XA 결과 처리에 관한 별도 보고다. 로컬 증거는 지정된 PostgreSQL/MySQL 프로파일의 단일 JDBC 트랜잭션 범위다. XA, 고객 장애 대응, 다른 DB·드라이버 조합은 미검증이다. [pgjdbc #4438](https://github.com/pgjdbc/pgjdbc/issues/4438) · [커밋 응답 유실 증거](../../evidence/PRODUCT-G5-FAILURE.json) |

## 후속 고객 검증 절차

대상 팀의 승인을 받아 격리 환경에서 업무 흐름, 변경·대조군, 기대 결과와 검토 범위를 사전에 고정한다. 기존 절차와 UDAK를 적용한 절차에 같은 변경과 판정 기준을 적용한다. 각각 설정 시간과 검토 시간, 검토 범위와 전체 대상 건수, 실제 발견·오탐·미검출 건수, 확인하지 못한 범위를 기록한다. 참여 역할, 합성 사례 ID, 소요 시간과 집계만 남긴다. SQL 원문, 입력·결과 데이터, 원본 식별자, 계정·자격 증명과 원본 로그는 수집 범위에서 제외한다.

서로 다른 프로젝트 3곳에 Observe를 적용하고 업무 코드 변경 라인 수와 회귀 결과를 측정하는 실험은 미충족이다. 고객 검증에서 현재 절차 대비 편익과 비용을 확인해야 제품화 여부를 판단할 수 있다.

## 상용 판단 실험

- 서로 다른 프로젝트 3개에 Observe 모드 도입, 업무코드 변경 라인 수/회귀 결과 측정
- 복잡 SQL 100건 SQL inventory 분류 및 실제 타겟 DB 테스트 비용 비교
- 신규 DSL 대비 jOOQ 직접 사용의 개발시간/코드 변경량 비교
- 라이선스 및 운영 부담 평가

**Go/No-Go:** 기존 도구만으로 달성하는 편익 대비 UDAK 추가 개발/운영 비용이 낮을 때만 제품화.

공식 참고: https://www.jooq.org/ ; https://mybatis.org/mybatis-dynamic-sql/docs/introduction.html ; https://docs.spring.io/spring-data/jpa/reference/
