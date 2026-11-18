# Legacy Compatibility — JPA / MyBatis / JdbcTemplate

[English](../en/05-LEGACY-COMPATIBILITY.md) | 한국어

## 1. 정책

기존 업무 소스의 동작을 바꾸지 않는 **OBSERVE**가 기본이다. `ANALYZE`는 SQL 호환성을 보고한다. `REWRITE`는 승인과 실제 회귀 테스트가 확보된 특정 Query에만 적용한다.

## 2. Integration adapter별 경계

### JPA/Hibernate
- `StatementInspector`는 SQL 문자열을 검사하는 지점이며 복잡한 바인딩/결과 구조 변환의 범용 해법이 아니다.
- JDBC/DataSource 경계에서 실제 SQL을 관측하는 방식이 간섭을 줄일 수 있다.
- JPA의 flush, 1차 캐시, lazy loading, dirty checking 등은 JPA 책임.
- 기존 JpaRepository와 Entity를 재작성하지 않음.

### MyBatis
- Mapper XML·`@Mapper` 그대로 유지.
- MappedStatement ID, BoundSql와 실행시 SQL 정보를 식별.
- Interceptor는 캐시 키/ParameterMapping/ResultMap을 깨뜨릴 수 있어 MVP에서 관측 중심.
- 동적 SQL은 **최종 바인딩된 구조별** Fingerprint와 계약 검증 필요.

### JdbcTemplate
- Spring JDBC 실행 경로의 DataSource/Connection boundary에서 관측.
- SQL 치환은 ? parameter count/order/column label/RowMapper 영향까지 검증해야 함.
- 기존 JdbcTemplate.query/update 사용법 유지.

## 3. 승인 기반 변환 단계

1. 기존 SQL 식별: framework + query id + source SQL / fingerprint
2. SQL parser/provider 판별: parse 지원 여부
3. Capability + bind/result contract 검사
4. 테스트용 원본/변환 쿼리 각각 실행
5. 입력·출력·시간·동시성 회귀 증거 확보
6. 승인 Registry에 provider/dialect/schema/SQL 버전 기록
7. 운영 활성화: 특정 Query만 허용, mismatch 시 fail closed
8. rollback: 해당 Query 룰만 비활성화하고 이전 승인 규칙 복원

## 4. 승인 예시 (설계안, 런타임 파일 처리 미구현)

```yaml
legacy:
  default-mode: observe
  rewrite:
    enabled: false
    approvals:
      - query-id: UserMapper.selectUsers
        framework: mybatis
        sql-sha256: '...'
        source-dialect: mysql-8
        target-dialect: oracle-19
        schema-revision: v3
        sql-provider-version: validated-version
        evidence-id: COMPAT-USER-001
        review-revision: r1
```

## 5. 변환하지 말아야 할 기본 범위

DDL, stored procedure, dynamic DDL, SQL hint, lock hint, vendor-specific types, uncontrolled native SQL, write statement with side effects, JPA association fetching rewrites.

## 6. Rollback

Bridge를 OFF로 전환할 수 있어야 한다. SQL rewrite는 설정 토글 외에도 승인 Registry를 버전 제어하고, 배포 단위별 rollback evidence가 필요하다. 일시적 오류 시 임의 원문 SQL 폴백은 기본 금지.

## Phase 3 구현 및 검증

HibernateObserveInspector·MyBatisObserveInterceptor·ObserveDataSource를 명시적으로 등록하는 경로를 구현했다. 기존 Entity/Repository/Mapper/service 4개 소스는 수정하지 않았다. 실제 H2와 PostgreSQL·MySQL·SQL Server·Oracle에서 Observe OFF/ON의 flush/cache/commit/rollback·매핑을 비교해 PASS했다. SQL 변환이나 자동 flush/cache 수정은 수행하지 않는다. 지점별 이벤트는 호출/prepare/execute 시도의 의미이며 전체 DB 성공 횟수가 아니다. [Phase 3 결과](21-LEGACY-OBSERVE-RESULTS.md)와 [G3 증거](../../evidence/PHASE3-GATE.json)를 따른다.

## Phase 5 명시적 JDBC 적용

기존 경로는 Observe 기본이다. 애플리케이션이 별도로 `SelectiveJdbcClient`를 호출하는 경우에만 승인된 canonical PostgreSQL paging SELECT를 실행한다. 거부된 호출의 SQL 준비는 0회이며, 원문 fallback은 수행하지 않는다. 승인 폐기는 최종 승인 검사 이전에 새 진입을 차단한다. 이미 진입한 실행은 완료될 수 있다. JPA·MyBatis 자동 변환과 flush/cache 동기화는 범위 밖이다. 고정 fixture의 실DB 동등성 검증과 G4는 PASS다. 운영 승인은 별도다. [Phase 5 결과](23-SELECTIVE-REWRITE-RESULTS.md)
