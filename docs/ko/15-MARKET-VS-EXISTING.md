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

## 상용 판단 실험

- 서로 다른 프로젝트 3개에 Observe 모드 도입, 업무코드 변경 라인 수/회귀 결과 측정
- 복잡 SQL 100건 SQL inventory 분류 및 실제 타겟 DB 테스트 비용 비교
- 신규 DSL 대비 jOOQ 직접 사용의 개발시간/코드 변경량 비교
- 라이선스 및 운영 부담 평가

**Go/No-Go:** 기존 도구만으로 달성하는 편익 대비 UDAK 추가 개발/운영 비용이 낮을 때만 제품화.

공식 참고: https://www.jooq.org/ ; https://mybatis.org/mybatis-dynamic-sql/docs/introduction.html ; https://docs.spring.io/spring-data/jpa/reference/
