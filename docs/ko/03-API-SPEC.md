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
