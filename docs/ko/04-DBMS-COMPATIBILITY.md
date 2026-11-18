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

## G2 드라이버 후보와 현재 판정

검증용 고정 버전·라이선스·전용 연결 계약은 [전용 실DB G2](19-REAL-DB-G2.md)와 [manifest](../../tools/g2-dependencies.json)가 SSOT다. 드라이버 로딩 PASS는 실DB 지원 선언이 아니다. 네 실DB 최소 기능 G2는 PASS이며 [실제 결과와 플랫폼 한계](20-MANAGED-G2-RESULTS.md)를 따른다.
