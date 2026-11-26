# API / SPI 계약서

[English](../en/03-API-SPEC.md) | 한국어

## 1. 사용 시나리오

### JOIN을 지원하는 Fluent SELECT (T-007)

```java
var db = new SelectClient(vendor, executor, List.of(
    new TableDefinition("users", List.of("id", "name", "department_id", "status"), "id"),
    new TableDefinition("departments", List.of("id", "name"), "id")));
var user = db.table("users", "u");
var department = db.table("departments", "d");

record UserDepartment(String userName, String departmentName) {}
List<UserDepartment> rows = db
    .select(user.column("name").as("user_name"), department.column("name").as("department_name"))
    .from(user)
    .innerJoin(department, user.column("department_id").equalTo(department.column("id")))
    .whereEqual(user.column("status"), "ACTIVE")
    .orderBy(user.column("id"), false)
    .page(20, 0)
    .fetch((row, rowNum) -> new UserDepartment(
        row.getString("user_name"), row.getString("department_name")));
```

- `SelectClient(DbVendor vendor, SqlExecutor executor, List<TableDefinition> tables)`를 생성할 때 물리 테이블과 컬럼의 허용 목록을 명시한다. 클라이언트는 모든 쿼리에 이 허용 목록을 적용한다. `table(name, alias).column(name)`으로 테이블 참조에 속한 컬럼을 가져온다. 물리 테이블명과 컬럼명은 검증한 뒤 따옴표 없이 렌더링한다. 테이블 별칭과 결과 라벨의 인용 방식은 DBMS 프로파일을 따른다.
- `innerJoin`과 `leftJoin`은 하나 이상의 컬럼 동등 조건을 받아 `AND`로 연결한다. 각 조건은 새 조인 대상과 이미 쿼리에 포함된 테이블 참조를 연결한다. 연쇄 조인과 서로 다른 별칭을 쓰는 자기 조인을 지원한다. 쿼리 내 테이블 별칭은 고유해야 한다. 조회 컬럼의 결과 라벨이 겹치면 `as(label)`로 구분한다.
- `whereEqual(column, value)`은 null이 아닌 값을 바인딩하고 `whereIsNull(column)`은 `IS NULL`을 생성한다. 필터가 여러 개면 `AND`로 연결한다.
- `orderBy(column, descending)`에서 `false`는 오름차순, `true`는 내림차순이다. `page(limit, offset)`에는 명시적 정렬이 필요하다. 정렬에 포함되지 않은 설정 ID 컬럼은 동률을 구분하는 오름차순 기준으로 추가한다. 설정한 각 ID는 해당 테이블에서 행을 고유하게 식별해야 한다.
- `fetch(RowMapper<T> mapper)`는 설정한 실행기를 통해 `List<T>`를 반환한다. 호출자는 `CrudClient`와 같은 `RowMapper` 계약에 따라 매퍼를 전달하며, 매퍼에서 결과 라벨로 값을 읽을 수 있다.

`CrudClient`는 생성·수정·ID 정책을 명시하는 Simple API를 별도로 제공한다.

테이블 별칭과 결과 라벨은 ASCII 30바이트 이하이며 각 범위에서 대소문자를 구분하지 않고 고유해야 한다. 행 번호 라벨 `udak_rn`은 예약되어 있다. 페이지 크기는 1~1,000이고 오프셋은 0 이상이다. Oracle 11g 프로파일은 오프셋과 페이지 크기의 합이 signed long 범위를 넘으면 거부한다.

[렌더링 프로파일과 실행 범위](04-DBMS-COMPATIBILITY.md#join을-지원하는-fluent-select-t-007)를 참고한다.

`python3 -B tools/run-fluent-join.py`로 보호된 기능 검증을 실행한다. [Fluent JOIN 증거](../../evidence/FLUENT-JOIN-VALIDATION.json)

### 기존 호환 (목표)

```java
userJpaRepository.findById(id);
userMapper.selectById(id);
jdbcTemplate.queryForObject(sql, mapper, id);
```

이 코드들은 기본적으로 변경하지 않는다.

## 2. 현재 core에서 실제 구현된 SPI

| 타입 | 목적 | 구현 수준 |
|---|---|---|
| `SqlCompiler` | QueryDefinition → CompiledQuery | 구현 |
| `BasicSqlCompiler` | 공통 subset SQL 생성 | 구현 (POC 한정) |
| `DbVendor` | 5개 vendor/profile | 구현 |
| `QueryDefinition` | SELECT with equality/sort/page | 구현 |
| `CompiledQuery` | SQL+ordered binds+vendor | 구현 |
| `ApprovedRewriteGuard` | 정확한 SQL 해시+ID+소스/대상+revision 승인 검사 | 구현 (실제 변환 없음) |
| `ConsistencyGuard` | 단일 로컬 DataSource 정책 검증 | 구현 (정적 설정 검사) |

### 현재 Java SPI 코드

```java
public interface SqlCompiler {
    CompiledQuery compile(QueryDefinition query, DbVendor vendor);
}
public record CompiledQuery(String sql, List<Bind> binds, DbVendor vendor) {}
```

`BasicSqlCompiler`는 자유 SQL 파서를 제공하지 않는다. 테이블/컬럼은 명시적 Allowlist가 필수다.

## 3. 목표 공개 API 제안

| API | 입력 | 반환 | 주의 |
|---|---|---|---|
| `findById` | Table/ID | `Optional<T>` | ID 정책 명확화 |
| `select` | typed columns | `SelectBuilder` | 현재 `SelectClient`는 1절의 T-007 범위를 지원 |
| `insertInto` | typed table | `InsertBuilder` | 생성 키 DB별 차이 |
| `update` | typed table | `UpdateBuilder` | WHERE 없음 기본 차단 |
| `deleteFrom` | typed table | `DeleteBuilder` | WHERE 없음 기본 차단 |
| `nativeSql` | SQL + binds | `NativeQuery` | 기본 무변환 |
| `fetchPage` | request + sort | `PageResult<T>` | 결정적 ORDER BY 필요 |

## 4. Query Compiler/Translator 구분

`SqlCompiler`는 신규 내부 AST를 렌더링한다. `SqlTranslator`는 이미 존재하는 원본 SQL을 parse+rewrite한다. 둘을 같은 인터페이스에 합치지 않는다.

목표 `CompiledQuery`는 SQL text, positional binding descriptors, expected result columns, SQL/dialect version, capabilities 정보를 가진다. 사용자 바인딩 **값**은 plan cache에 보관하지 않는다.

## 5. SQL Fingerprint/승인 계약

승인 키: Query ID + SQL exact bytes/hash + source/target dialect/profile + schema version + provider version + approval revision + verified evidence ID.

현재 POC는 일부(`queryId`, exact SQL hash, source/target, reviewRevision)만 구현했다. 나머지는 제품화 시 필수 추가.

## 6. 예외 설계 (목표)

- `UdakCompileException`
- `UnsupportedDialectFeatureException`
- `UnapprovedRewriteException`
- `QueryContractMismatchException`
- `ConsistencyConfigurationException`

예외는 민감한 SQL 바인딩 값을 기본 메시지에 포함하지 않는다.

## 7. Phase 1에서 검증한 Compiler 계약

- null query/vendor와 잘못된 식별자·페이지 범위는 거부한다. 모든 table/column/order 식별자에 allowlist를 적용하고 사용자 값은 SQL에 인라인하지 않는다. null 필터 값도 bind로 전달하며 SQL NULL 비교 의미의 자동 변환은 제공하지 않는다.
- 입력 column과 출력 bind 목록은 얕은 불변 snapshot이다. bind 값 객체 자체는 깊은 복사하지 않는다. 같은 입력의 SQL·vendor·bind 이름/값/순서는 결정적이어야 한다.
- `sql-jsqlparser`의 `JSqlParserValidatingCompiler`는 기본 컴파일러 결과를 upstream JSqlParser 5.4의 statement-list parser로 검사하고 정확히 하나의 SELECT만 허용한다. SQL·bind를 다시 쓰지 않으며 외부 parser 타입을 Core에 노출하지 않는다.
- SQL 길이는 16,384자, 공유 daemon 작업자는 1개, 대기열은 1개, 파싱 시도별 timeout은 1초다. 파서 내부 재시도가 있을 수 있고 취소는 협조적이므로 호출 전체 1초 또는 강제 스레드 종료를 보장하지 않는다. 포화·오류 시 닫힌 상태로 실패하며 예외에는 원문·값·cause를 남기지 않는다.
- 동일한 `CompilerContractTest`를 기본·외부 구현에 적용한다. 실제 실행 증거와 재현 명령은 [Phase 1 결과](14-POC-RESULTS.md)를 따른다. 파싱 성공은 실DB 실행·결과 동등성이나 기존 SQL 번역의 증거가 아니다.

## 8. Phase 2 최소 CRUD / JDBC 계약

`udak-api`는 JDK와 Core만 사용한다. `TableDefinition(table, columns, idColumn)`의 테이블별 allowlist·선언 column 순서를 기준으로 `CrudClient`가 INSERT/UPDATE/DELETE와 기존 equality/sort/page SELECT를 구성한다. 모든 값은 bind이며 삽입 ID는 호출자가 제공한다. ID 없는 수정·삭제, PK 수정, 미허용 식별자·빈 변경은 거부한다. 생성 키·UPSERT·전체 Fluent DSL은 범위 밖이다.

`RowMapper<T>.map(ResultSet, rowNum)`은 열린 행에서 값을 읽고 non-null 객체를 반환한다. JDBC label·SQL NULL·primitive getter 의미를 숨기지 않는다. `findById`는 두 행까지 확인하여 중복을 거부하고 목록 snapshot은 얕다.

`jdbc-spring`의 실행기는 원본 DataSource의 Spring transaction binding을 사용하며 자체 commit/rollback은 하지 않는다. timeout 1~30초·행 수 1~1000 제한과 초과 행 감지를 적용한다. SQL 방화벽이 아닌 trusted `CompiledQuery` 실행 경계다. Executor 내부 예외·해제 경로는 정제하며 외부 driver/DataSource/TransactionManager 로그까지 통제하지 않는다.

구체 API와 최초 기반 검증은 [CRUD/JDBC 검증](18-CRUD-JDBC-VALIDATION.md)을 따른다. 당시 4 실DB는 NOT RUN/G2 미완료였으며, 이후 전용 provider 실행으로 [실제 G2](20-MANAGED-G2-RESULTS.md)를 통과했다.

## 9. 구현된 Observe 계약 (Phase 3)

`observe-core`는 JDK 전용이다. `SqlObserver.observe(Framework, ObservationPoint, queryId, sql)`은 동기식 `ObservationSink`에 불변 `SqlObservation`을 전달한다. 이벤트는 framework, point, queryIdHash, fingerprintHash, statementKind, fingerprintStatus만 담고 원 SQL·값·접속정보·예외를 담지 않는다.

| 경계 | 구현 계약 |
|---|---|
| Fingerprint | 최대 SQL 16,384자·ID 256자; 보수적 어휘 형태 해시; 모호/미지원은 UNAVAILABLE 고정 해시 |
| 승인 | 기존 정확 SQL `SqlFingerprint.sha256`는 그대로 유지; Observe 해시는 승인 키로 사용하지 않음 |
| Hibernate | StatementInspector가 받은 원 String을 그대로 반환 |
| MyBatis | query 4/6·update 문맥의 최근 ID와 이미 완성된 BoundSql을 prepare에서 관측; 캐시 키/인수/ResultMap 유지 |
| JDBC | 명시적으로 공유한 ObserveDataSource에서 execute 시도만 관측; ResultSet/RowMapper와 자원 동작은 위임 |
| Listener | 동기·thread-safe/nonblocking은 수신자 책임; 비치명 실패 격리, interrupt 보존, VM/ThreadDeath 전파 |

반드시 같은 wrapper DataSource를 EntityManagerFactory·JpaTransactionManager·MyBatis·JdbcTemplate에 공급한다. 원본 DataSource/풀의 수명은 기존 소유자가 관리한다. cursor/내부 nested ID, vendor unwrap/builder와 ResultSet/metadata 역참조, plain Statement batch SQL에는 관찰 공백이 있다. [구체 범위와 검증](21-LEGACY-OBSERVE-RESULTS.md)을 따른다.

## 10. 명시적 트랜잭션 진단 (Phase 4)

`dev.udak.consistency.TransactionGuard`는 enum 중심 Intent/Snapshot/Report 계약을 정의하고 `dev.udak.consistency.spring.SpringConsistencyGuard`는 제공된 구성과 현재 스레드 holder를 검사한다. `inspectConfiguration`·`inspectTransaction`은 위험을 보고하며 명시적 `requireAllowed()`가 ERROR를 차단한다. [연결·경계·검증 상태](22-TRANSACTION-GUARD-RESULTS.md)를 따른다. 기존 Core 정적 guard와 정확 승인 해시는 유지한다.

## 11. 명시적 선택 변환 API (Phase 5)

운영자가 `Rewrite.Registry`에 `Approval` 및 `Evidence`를 등록하고, `PaginationRewriteProvider`와 함께 `SelectiveJdbcClient(DataSource, Environment, Registry, Provider)`에 연결한다. `query(Template, Parameters, RowMapper)`는 정확 원문과 환경에 묶인 `Plan`만 실행한다. `Parameters(filter, limit, offset)` 범위는 문자열 최대 1,024자 또는 NULL, 1–1,000, 0–1,000,000이다. JDBC 시간 제한은 5초다. 입장 전 정책 거부는 `Rewrite.Denied`, 정제된 실행 장애는 `SelectiveJdbcClient.SafeJdbcException`으로 전달된다. 로컬 계약과 고정 fixture의 실DB 동등성 검증은 PASS다. [Phase 5 결과](23-SELECTIVE-REWRITE-RESULTS.md)
