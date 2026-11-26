# Database Compatibility Matrix & Dialect Policy

[English](../en/04-DBMS-COMPATIBILITY.md) | 한국어

## 1. 대상

- PostgreSQL (최소 주요 버전은 실DB 테스트 후 확정)
- MySQL 8.x 이상 후보 (실DB 테스트 후 확정)
- SQL Server 2019/2022 등 후보 (라이선스/버전 테스트 후 확정)
- Oracle 19c 이상 후보; Oracle 11g는 별도 Legacy 프로파일

**SQL 생성 테스트 통과는 DBMS 지원 인증이 아니다.** 실제 Driver·Server·Collation·Schema·Transaction 검증이 필요하다.

## 2. 기본 SQL 비교

| 기능 | PostgreSQL | MySQL | SQL Server | Oracle |
|---|---|---|---|---|
| Pagination | `LIMIT/OFFSET` | `LIMIT/OFFSET` | `OFFSET...FETCH` + ORDER BY | 12c+ `OFFSET...FETCH`, 11g ROWNUM |
| Upsert | ON CONFLICT | ON DUPLICATE KEY | 별도 안전 전략 | MERGE 등 |
| Identity/sequence | identity/sequence | auto_increment | identity/sequence | version-dependent |
| Boolean | BOOLEAN | TINYINT(1) alias 취급 | BIT | 버전별 타입/매핑 |
| JSON | JSON/JSONB | JSON | 기능별 확인 | 버전별 확인 |
| Case/collation | DB locale 의존 | collation 의존 | collation 의존 | NLS/collation 의존 |
| Timestamp | TZ-aware / without TZ | 세션/타입 의존 | datetimeoffset 등 | timestamp w/ TZ 등 |

## 3. 공통 SQL 지원 Tier

- Tier-A: 기본 비교/조건/내부 JOIN/ORDER/BASIC PAGE
- Tier-B: LEFT JOIN, GROUP, aggregation, generated key, batch, locking
- Tier-C: CTE, window, JSON, arrays, MERGE, procedural SQL

MVP는 Tier-A부터 실제 테스트. B/C는 기능별 Capability와 provider별 조건을 명시.

## 4. 주의할 의미 차이

- `NULL`과 빈 문자열: Oracle의 빈 문자열 처리 등
- timezone: `LocalDateTime`은 순간(instant)을 뜻하지 않음
- isolation: 데이터베이스별 기본 격리 수준 다름
- `LIKE`, 대소문자 및 정렬 결과: collation에 의존
- generated keys: identity/sequence 방식 차이
- transaction DDL: DB별 자동 commit/implicit behavior 차이
- execution plans: SQL이 같아도 성능 다름

## 5. Oracle 11g 별도 취급

POC의 `ORACLE_11` ROWNUM 코드는 SQL string/binding order 시연용이다. 실제 11g DB에 연결해 검증하지 않았다. Hibernate 최신 버전으로 Oracle 11g를 직접 지원한다고 주장하지 않는다.

## 6. 검증 증거

필드: `dbms`, `server_version`, `driver_version`, `sql_engine`, `schema_version`, `query_id`, `sql_hash`, `input_dataset`, `output_hash`, `performance_baseline`, `test_result`.

## JOIN을 지원하는 Fluent SELECT (T-007)

T-007은 명시적 INNER·LEFT JOIN, ON 절의 컬럼 동등 조건, WHERE 값 바인딩, 정렬 페이지를 다룬다. 물리 테이블명과 컬럼명은 설정한 허용 목록에서 가져오며 따옴표 없이 렌더링한다. 테이블 별칭과 결과 라벨의 인용 방식은 아래와 같다.

| 렌더링 프로파일 | 별칭·라벨 인용 방식 | 페이지 구문 | 페이지 바인딩 순서 |
|---|---|---|---|
| `POSTGRESQL` | 큰따옴표 | `LIMIT ? OFFSET ?` | limit, offset |
| `MYSQL` | 백틱 | `LIMIT ? OFFSET ?` | limit, offset |
| `SQLSERVER` | 대괄호 | `OFFSET ? ROWS FETCH NEXT ? ROWS ONLY` | offset, limit |
| `ORACLE_19` | 큰따옴표 | `OFFSET ? ROWS FETCH NEXT ? ROWS ONLY` | offset, limit |
| `ORACLE_11` | 큰따옴표 | 정렬한 서브쿼리, `ROWNUM` 상한, 바깥 쿼리의 하한 | offset + limit, offset |

WHERE 값은 페이지 값보다 먼저 바인딩한다. `ORACLE_11` 페이지 쿼리는 내부 쿼리에서 행을 정렬한 다음 이를 감싸는 쿼리에서 행 번호를 매긴다. 바깥 쿼리는 이 행 번호로 정렬하고 요청한 결과 라벨만 조회한다.

T-007은 다섯 프로파일의 렌더링과 H2, PostgreSQL 17.11·PgJDBC 42.7.14, MySQL 8.0.46·Connector/J 26.10.0의 실행을 검증했다. 같은 Spring JDBC fixture에서 복합 조인, NULL 결과, 값·페이지 바인딩 순서와 롤백을 확인했다. SQL Server와 Oracle JOIN은 렌더링 범위이며 실DB 실행은 미실행이다. 아래 G2 표는 최소 CRUD와 트랜잭션 검증을 다룬다. [JOIN 실DB 증거](../../evidence/FLUENT-JOIN-REAL-DB-VALIDATION.json)

## G2 드라이버 후보와 현재 판정

검증용 고정 버전·라이선스·전용 연결 계약은 [전용 실DB G2](19-REAL-DB-G2.md)와 [manifest](../../tools/g2-dependencies.json)가 SSOT다. 드라이버 로딩 PASS는 실DB 지원 선언이 아니다. 네 실DB 최소 기능 G2는 PASS이며 [실제 결과와 플랫폼 한계](20-MANAGED-G2-RESULTS.md)를 따른다.
