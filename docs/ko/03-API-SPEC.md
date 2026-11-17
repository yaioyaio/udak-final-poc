# API / SPI 계약서

[English](../en/03-API-SPEC.md) | 한국어

## 1. 사용 시나리오

### 신규 Fluent API (목표 API, 아직 구현되지 않음)

```java
List<UserDto> list = db.select(USER.ID, USER.NAME)
    .from(USER)
    .where(USER.STATUS.eq("ACTIVE"))
    .orderBy(USER.ID.desc())
    .limit(20)
    .fetch(UserDto.class);
```

Simple API는 별도 `CrudClient<T,ID>`로 구성한다. JPA Entity의 `save()` semantics를 그대로 모방하지 않고 신규/수정·ID 생성 정책을 명시한다.

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
| `select` | typed columns | `SelectBuilder` | SQL AST 생성 |
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
