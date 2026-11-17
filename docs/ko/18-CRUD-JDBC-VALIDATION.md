# Phase 2 CRUD / JDBC 검증

[English](../en/18-CRUD-JDBC-VALIDATION.md) | 한국어

## 1. 범위와 완료 판정

P2-API / FR-002·014 / T-006, P2-EXEC / FR-010 / T-008, P2-DB-BASE / FR-003·011 / T-009·010 및 P2-HARNESS의 최소 구현·기반 검증 결과다. [추적표](16-TRACEABILITY.md)와 [API 계약](03-API-SPEC.md)을 함께 따른다.

[PHASE2-VALIDATION.json](../../evidence/PHASE2-VALIDATION.json)의 PASS는 최소 API, 실제 Spring JDBC/H2 Executor와 실DB 검증 기반 범위다. **전체 Phase 2 G2는 NOT PASSED**이며 네 실DB 검증을 완료했다는 뜻이 아니다. 기존 SQL은 Observe 기본, 승인 없는 Rewrite 금지를 유지한다.

## 2. 최소 API 계약

| API | 입력·결과 | 경계 |
|---|---|---|
| `insert` | column/value map → 영향 행 수 | 호출자가 non-null ID 제공 |
| `updateById` | non-null ID + column/value map → 영향 행 수 | PK 변경 금지; 빈 변경 거부 |
| `deleteById` | non-null ID → 영향 행 수 | ID 없는 삭제 금지 |
| `findById` | ID + 명시적 `RowMapper` → `Optional<T>` | 최대 두 행으로 중복 검출; mapper null 반환 거부 |
| `select` | `QueryDefinition` + 명시적 `RowMapper` → `List<T>` | 현재 equality/sort/page subset |

`TableDefinition`은 table별 column·ID allowlist와 column 순서를 정의한다. 조회 table/column/filter/order는 이 범위에서 검사하며 값은 positional bind로 전달한다. INSERT·UPDATE는 입력 map 순서와 무관하게 선언 column 순서를 따르고 UPDATE의 ID bind는 마지막이다. 조회 bind 순서는 compiler 계약을 따른다.

SELECT 경로는 기존 기본 compiler를 유지하며 4인자 `CrudClient` 생성자로 `SqlCompiler`를 주입할 수 있다. 테이블별 식별자 검사는 공급자 호출 전에 수행한다. INSERT/UPDATE/DELETE는 이 최소 계약의 공통 DML 생성 경로를 사용한다.

입력 map·column 목록·결과 목록의 snapshot은 얕다. 값 객체는 복사하지 않는다. SQL NULL 값은 bind할 수 있지만 equality를 `IS NULL`로 자동 변환하지 않는다. UPSERT·generated key·자동 ID 생성·ORM lifecycle/cache/flush는 제공하지 않는다.

`RowMapper`는 열린 JDBC `ResultSet`의 현재 행을 `map(row, rowNum)`으로 처리한다. ResultSet이나 그 수명에 종속된 객체를 반환·보관하지 말고 필요한 값을 mapper 안에서 읽는다. column label은 JDBC/driver가 제공하는 실제 label을 사용하며 자동 대소문자 변환·DTO 반사는 없다. `getObject`/`getString`의 SQL NULL과 primitive getter의 기본값·`wasNull()`을 구분하고, 행 객체 자체는 non-null로 반환한다.

## 3. Spring Executor와 보안 경계

`SpringJdbcExecutor`는 외부 주입 원본 `DataSource`를 그대로 사용한다. `DataSourceUtils.getConnection` / `doReleaseConnection`으로 같은 DataSource의 Spring 트랜잭션 연결에 참여하고, Statement·ResultSet은 닫되 transaction-bound Connection의 종료는 Spring에 맡긴다. 별도 DataSource wrapper나 자체 commit/rollback은 만들지 않는다. [Spring 연결 관리 공식 참고](https://docs.spring.io/spring-framework/reference/6.2/data-access/jdbc/connections.html).

query timeout은 1~30초, 결과 한도는 1~1000행이며 기본값은 5초·1000행이다. `maxRows + 1` sentinel을 요청하고 한도 초과는 잘라 반환하지 않고 거부한다. 외부 Spring TX 잔여 deadline과 설정 timeout 중 작은 값을 적용한다. JDBC timeout은 driver 기능에 의존하며 연결 획득·네트워크 전체의 강제 종료 시간 보장은 아니다.

값은 `PreparedStatement.setObject`로 bind한다. Executor 내부 실행·매핑·해제 실패는 SQL·값·연결정보·원래 cause 없는 고정 메시지 `SafeJdbcException`으로 내보내며 값이 기록될 수 있는 Spring parameter helper/예외 translator 경로를 사용하지 않는다. 이는 **Executor 내부 경로의 보장**이다. 외부 DataSource·driver·TransactionManager의 DEBUG/TRACE logging과 호출자 mapper의 부수효과는 통제하지 못하므로 외부 로그 정책은 별도로 적용해야 한다.

단일 DataSource의 Spring commit/rollback 참여 증거이며 여러 DBMS 원자적 commit이나 JPA flush/cache 자동 동기화 보장이 아니다. Boot3/Boot4 Starter 지원 검증을 대신하지 않는다.

## 4. 실제 검증과 버전

| 검증 | 실제 결과 |
|---|---|
| Core smoke | PASS |
| Phase 1 기본·외부 compiler 회귀 | PASS: 74 / 83 assertions |
| 최소 CRUD API | PASS: 313 assertions |
| Spring JDBC / H2 | PASS: CRUD·NULL·bind·commit/rollback·자원 회수·민감 예외 경로 |
| DB foundation / H2 | PASS: 45 assertions |
| 정리 probe | PASS: failure / timeout / signal / exception / descendant, 5개 |
| PostgreSQL / MySQL / SQL Server / Oracle | 모두 NOT RUN: DEDICATED_PROVIDER_REQUIRED |

Java 컴파일 대상은 17, 실제 runtime은 보고서의 `java_runtime_version`(현재 21.0.13)이다. Spring 6.2.19 / H2 2.3.232를 고정했고 Spring Boot 3.5.16 BOM 정합성을 확인했다. artifact checksum·POM 의존성/라이선스·notice 검사는 PASS이며 Spring은 Apache-2.0, H2는 MPL-2.0 선택이다. 이는 제품 배포 승인이나 새 실DB driver 라이선스 승인 완료가 아니다.

H2는 Executor와 fixture 절차의 실행 증거다. H2 compatibility mode나 SQL 렌더링 성공은 네 실DB 호환성 증거가 아니다. Gradle task, Spring Boot/JPA/MyBatis demo, 성능·부하 시험, 제품 배포 승인은 NOT RUN이다. 실제 실행은 `javac`/`java`와 embedded H2이며 컨테이너 시작·기존 컨테이너 변경·보조 worktree 생성/회수는 모두 0개다.

## 5. 실DB 검증 기반과 보존 정책

인자 없는 `RealDatabaseContractRunner` inventory는 접속하지 않는다. 명시적 실행에는 `ServiceLoader`의 단일 `RealDatabaseProvider`가 `profile()`·`dataSource()`·`dedicatedSchemaApproved()`를 제공해야 한다. 후보 driver class의 classpath 존재와 JDBC metadata product 일치를 확인한 후에만 시나리오를 실행한다. 후보 class/product 확인은 실제 server/driver 버전 지원 선언이 아니다. 새 실DB driver는 자동 다운로드하지 않으며 버전·라이선스 승인은 미완료다.

시나리오는 전용 승인 schema 안의 소유 fixture `udak_p2_` + 12자리 hex에만 CREATE/DROP한다. CRUD·NULL·페이지·injection-like bind·commit/rollback 후 정리를 확인한다. CREATE 성공을 확인하지 못하면 `CREATION_UNCONFIRMED`, 소유 fixture DROP 성공을 확인하지 못하면 `CLEANUP_UNCONFIRMED`이며 PASS 금지다. 해당 identifier를 결과에 보존하여 후속 확인하고 불명 객체를 임의 삭제하지 않는다. 기존 DB·테이블·비밀 설정은 변경하지 않는다.

## 6. 재현과 다음 단계

```bash
python3 tools/run-phase2.py
```

Python 표준 라이브러리 실행기는 저장소 Root 정책과 기존 Phase 1 guard를 사용한다. wall 180초, 자식 CPU 30초, JVM heap 256MiB/metaspace 128MiB/active CPU 2개, 다운로드 파일당 5,000,000바이트, 임시 workspace 2,000파일/128MiB 상한이다. 고정 의존성 취득은 허용 Maven 출처·checksum으로 제한한다.

성공·실패·timeout·signal·예외·잔존 자식 probe에 실제 자동 정리가 연결된다. 보고서 기준 본 실행 임시 파일 60개/8,479,319바이트 회수, 잔여 디렉터리 0개이며 각 probe 임시 파일 1개/0바이트 회수를 확인했다. 실패 보고서는 다음 실행 전에 보존한다. 임의 외부 명령이나 Git 완료 이벤트 전체의 자동 정리를 검증한 것은 아니다.

다음 단계는 Phase 2 전용 네 실DB provider/profile 제공, driver 버전·라이선스 고정 후 제한 실행, 실제 결과·정리 증거로 G2 확인이다. **G2 통과 후 Phase 3에 진입한다.**

초기 권한 오류의 빈 진단 파일 1개/0바이트는 불명 자료로 별도 보존 중이다. 위 회수 수치는 최신 성공 workspace만 대상으로 하며 이 예외의 소유·미사용 확인 전 삭제하지 않는다.

## 실제 G2 후속 검증

드라이버·라이선스 고정 및 실제 연결 실행 절차는 [전용 실DB G2](19-REAL-DB-G2.md)를 따른다. 현재 네 실DB는 NOT RUN이며 G2는 INCOMPLETE다.
