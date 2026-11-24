# 스키마 변경 영향 분석과 쿼리별 실DB 회귀

[English](../en/27-SCHEMA-IMPACT-REGRESSION.md) | 한국어

제품 확장 Phase 3은 **PASS** 상태다. `SCHEMA-001`부터 `SCHEMA-003`까지 정규화된 스키마 비교, 고정 fixture 실DB 회귀, 자원을 제한하는 실행기를 다룬다. [추적성 및 검증 상태](16-TRACEABILITY.md)

## 정규화된 스키마 메타데이터 비교

버전이 있는 base/head 스키마 스냅샷, Phase 1의 head SQL 인벤토리, 쿼리 의존성을 명시한 head 매니페스트를 준비한다. 저장소 루트에서 지정된 파일명을 사용해 실행한다.

```bash
python3 tools/schema-impact.py \
  --base build/schema/base/SCHEMA-SNAPSHOT.json \
  --head build/schema/head/SCHEMA-SNAPSHOT.json \
  --inventory build/schema/head/SQL-INVENTORY.json \
  --dependencies build/schema/head/QUERY-DEPENDENCIES.json
```

| 입력 | JSON 필드 |
|---|---|
| `SCHEMA-SNAPSHOT.json` (base 및 head) | `schema_version` (정수 `1`), `revision`, `scope`, `columns`. 각 컬럼에는 `table`, `column`, `type`, `width`, `nullable` (불리언)이 들어간다. |
| `SQL-INVENTORY.json` (head) | `schema_version`, `revision`, `profile`, `dropped`, `entries`가 있는 Phase 1 인벤토리 스냅샷. 명시적으로 등록한 각 쿼리는 고정된 `query_id_hash`와 등록된 테스트 해시를 사용한다. |
| `QUERY-DEPENDENCIES.json` (head) | `schema_version` (정수 `1` 또는 `2`), `revision`, `scope`, `dependencies`. 각 의존성에는 `framework` (`JPA`, `MYBATIS`, `JDBC` 중 하나), 인벤토리의 `query_id_hash`, `table`과 `column` 쌍으로 이루어진 `columns`가 들어간다. 해당 테이블의 모든 컬럼 변경을 포함하려면 `column`에 `*`를 쓴다. |

base와 head의 `revision`은 각각 40자 또는 64자의 소문자 16진수이며 서로 달라야 한다. 두 스냅샷과 매니페스트에는 64자의 소문자 16진수로 된 같은 `scope`를 쓴다. head 스냅샷, 인벤토리, 매니페스트는 같은 head `revision`을 쓴다. 인벤토리의 `profile`은 스키마의 `scope`와 같아야 한다. `query_id_hash`도 64자의 소문자 16진수다. 테이블·컬럼 식별자는 소문자로 시작하며 이후 소문자, 숫자, 밑줄을 포함해 최대 63자까지 허용한다. 정규화 타입은 `INTEGER`, `BIGINT`, `VARCHAR`, `DECIMAL`, `BOOLEAN`, `DATE`, `TIMESTAMP`, `TEXT`, `UUID`다. `VARCHAR`의 `width`는 1~100,000이고 나머지 타입은 0이다.

CLI는 POSIX에서 크기 제한이 있는 로컬 JSON 파일을 읽기 전용으로 처리한다. 입력은 심볼릭 링크가 없는 상대 경로에 있는 하드 링크 수 1, 최대 1 MiB의 일반 파일이어야 한다. 스냅샷당 최대 4,096개 컬럼, v1 매니페스트당 최대 128개 쿼리, 의존성 행당 최대 128개 컬럼 참조를 허용한다. CLI 입력은 정규화된 메타데이터로 한정한다. DDL·마이그레이션·저장소 소스 파싱은 구현 범위 밖이며 CLI는 SQL을 실행하지 않는다. [Phase 1 인벤토리 계약](25-SQL-INVENTORY-PR-REPORT.md)

| 종료 코드 | 의미 |
|---|---|
| `0` | `COMPLETE`. 스키마 변경, 영향받는 쿼리 해시, 중복을 제거한 테스트 해시 목록 `impacted_test_ids`를 제공한다. 변경 유형은 `ADDED`, `REMOVED`, `TYPE`, `WIDTH`, `NULLABILITY`다. |
| `1` | 잘못된 인수 또는 입력. |
| `2` | `INCOMPLETE`. 확인된 변경과 영향은 보고서에 포함한다. 변경이 있는데 인벤토리가 비어 있거나, 관측 누락, 관측 정보 미확보, 관측 전용 임시 ID, 테스트·의존성 누락, 확인되지 않은 쿼리·참조가 있으면 비교 결과를 불완전으로 표시한다. |


## 관측된 지문별 의존성 검증

같은 범위의 Query ID에서 여러 SQL 지문을 관측하면 v2 매니페스트를 사용한다. `SCHEMA-SNAPSHOT.json`은 v1을 사용한다. `SQL-INVENTORY.json`은 v1과 v2를 지원한다. v2 의존성 행에 `fingerprint_hash`와 `test_ids`를 추가한다. 행의 키는 `framework` + `query_id_hash` + `fingerprint_hash` 조합이다. 각 해시는 64자 소문자 16진수다. 기존 1 MiB 입력 상한 안에서 v2는 최대 1,024개 행, 행당 최대 8개 테스트 해시를 허용한다. 행 키, 테스트 해시, 컬럼 참조의 중복은 오류다.

매니페스트를 입력하기 전에 관측된 지문별 컬럼 참조와 연결된 테스트를 검토한다. 인벤토리는 쿼리의 지문 목록과 전체 테스트 목록을 제공한다. CLI는 이 목록에 속하는지 확인하고 유효한 지문 행의 테스트 합집합이 등록된 쿼리 테스트 전체를 포함하는지 검사한다. v1 인벤토리의 지문별 테스트 연결은 검토된 매니페스트에서 읽는다. 실행 중 관측 기록으로 연결을 검증하려면 v2 인벤토리를 사용한다. 선언형 쿼리와 관측 지문이 하나인 쿼리는 기존 v1 계약을 따른다. 관측 지문이 여러 개인 쿼리에 v1 참조를 제공하면 기존 쿼리 단위의 보수적 테스트 선정을 유지하고 `INCOMPLETE`로 판정한다.

관측된 지문의 행이 빠졌거나 불완전하면 보고서의 `unresolved_queries[].fingerprint_issues`에 지문별 사유를 표시한다. 미관측 지문의 테스트는 선정에서 제외한다. 다른 지문의 의존성이 누락돼도 관측 지문에서 확인된 영향은 표시한다. 보고서는 기존 쿼리 단위 영향 항목을 유지하고 영향받은 지문에서 선정한 테스트 해시의 중복을 제거한다.

```bash
python3 -B tools/run-order-schema-impact.py --query-fingerprints
```

H2 하네스는 MyBatis 재고 UPDATE 두 분기를 한 Query ID로 실행하고 서로 다른 테스트 ID를 붙인다. OFF 실행 직후 인벤토리에서 OFF 지문을 확인하고, ON 실행 이후 합친 인벤토리에서 추가된 지문 하나를 확인한다. 두 의존성을 제공하면 `active` 변경에서 ON 테스트만 선정하고 미사용 컬럼 변경에서는 0건을 선정한다. 두 행 중 어느 하나를 빼면 `INCOMPLETE`다. OFF 행을 빼도 이미 확인된 ON 영향은 표시한다. 외부 DB 연동은 NOT RUN이다. [주문 지문 의존성 검증 증거](../../evidence/ORDER-FINGERPRINT-DEPENDENCIES-VALIDATION.json)

## 지문을 관측한 테스트 연결 검증

의존성 매니페스트와 인벤토리를 모두 v2로 제공하면 각 매니페스트 행의 테스트 집합이 해당 지문에서 실제로 관측된 테스트 해시와 일치해야 한다. 일치하지 않으면 `FINGERPRINT_TEST_MISMATCH`를 표시하고 `INCOMPLETE`로 판정한다. 변경에 영향받는 지문에서는 양쪽에 공통으로 있는 테스트만 선정한다. 쿼리 단위 테스트에 포함된 사실만으로 지문별 연결을 입증할 수 없다. 선언과 정규화 불가 기록도 지문별 연결의 증거가 될 수 없다.

```bash
python3 -B tools/run-order-schema-impact.py --observed-tests
```

H2 실행기는 개별 스코프에서 발생한 MyBatis 재고 지문을 대조한다. v2 인벤토리에는 각 지문을 실제로 관측한 테스트가 기록된다. 정상 연결의 활성 컬럼 변경은 ON 테스트만 선정한다. 쿼리 전체 테스트 집합을 유지한 채 두 연결을 바꾸면 두 지문에 불일치가 표시되고 선정은 0건이다. 미사용 컬럼 대조군은 0건을 선정하고 지문 행 누락은 불완전으로 남는다. 외부 DB 연동은 NOT RUN이다. [지문별 실제 관측 테스트 검증 증거](../../evidence/ORDER-OBSERVED-FINGERPRINT-TESTS-VALIDATION.json)

## 환경 간 스키마 계약 비교

NEXT-004는 호출자가 제공한 JDBC 연결에서 버전 1 정규화 컬럼 스냅샷을 수집한다. H2 2.3.232와 PostgreSQL 18·PgJDBC 42.7.14에서 검증했다. JDBC 카탈로그와 스키마의 정확한 이름을 지정하고 안정적인 논리 테이블명을 환경별 물리 테이블명과 매핑한다. 두 환경에 같은 논리 테이블 목록을 사용한다. 수집기는 JDBC 메타데이터만 읽으며 연결과 트랜잭션 상태는 호출자가 관리한다. [JDBC 컬럼 메타데이터](https://docs.oracle.com/en/java/javase/17/docs/api/java.sql/java/sql/DatabaseMetaData.html#getColumns(java.lang.String,java.lang.String,java.lang.String,java.lang.String))

```java
String snapshot = SchemaSnapshotCollector.collect(
        connection, revision, connection.getCatalog(), "PUBLIC",
        Map.of("contract_item", "CONTRACT_ITEM"));
Files.writeString(snapshotPath, snapshot, StandardOpenOption.CREATE_NEW);
```

기준·현재 JSON을 각각 정해진 파일명으로 저장한 뒤 저장소 루트에서 CLI를 실행한다. 두 스냅샷의 리비전은 같아도 된다. 범위 해시는 DBMS와 논리 테이블 목록을 묶는다. CLI는 해시와 실제 테이블 목록을 모두 검사한다.

```bash
python3 tools/schema-drift.py --dbms H2 --table contract_item \
  --baseline build/schema/baseline/SCHEMA-SNAPSHOT.json \
  --current build/schema/current/SCHEMA-SNAPSHOT.json
```

PostgreSQL 스냅샷을 비교할 때는 `--dbms POSTGRESQL`을 사용한다. PostgreSQL 수집은 지정된 일반·파티션 테이블과 소문자 컬럼명을 대상으로 한다. PgJDBC 타입 이름과 JDBC 코드를 함께 확인해 `uuid`는 `UUID`, `text`는 `TEXT`로 정규화한다. 시간대가 있는 타임스탬프나 드라이버의 지원 범위를 벗어난 타입은 수집을 실패 처리한다. `VARCHAR` 길이는 JDBC 메타데이터를 사용하며 PgJDBC 기본 설정에서 길이가 지정되지 않은 `VARCHAR`는 거부했다. [PgJDBC 타입 매핑](https://github.com/pgjdbc/pgjdbc/blob/REL42.7.14/pgjdbc/src/main/java/org/postgresql/jdbc/TypeInfoCache.java)

종료 코드 `0`은 `MATCH`, `2`는 `DRIFT`, `1`은 입력 또는 범위 오류다. 컬럼의 추가·삭제·타입·VARCHAR 길이·NULL 허용 여부 변화를 표시한다. 지정 테이블이 없거나 접근할 수 없거나 컬럼 메타데이터가 미지원이면 수집을 실패 처리한다. 지정 테이블은 최대 128개, 컬럼은 최대 4,096개다. 수집기는 H2의 일반 대문자 또는 소문자 식별자를 소문자로 정규화하고 대소문자 혼합 컬럼명은 거부한다. 출력에는 논리 식별자와 컬럼 정의가 포함되므로 공유가 승인된 식별자를 사용한다. 키, 인덱스, 기본값, DECIMAL 정밀도·스케일, 마이그레이션 이력과 쿼리 의존성 자동 추출은 이 계약의 범위 밖이다.

`python3 tools/run-schema-drift.py`는 H2의 같은 리비전에서 일치와 컬럼 변경 5종을 검증한다. [H2 검증 증거](../../evidence/SCHEMA-DRIFT-VALIDATION.json)

`python3 -B tools/run-postgresql-schema-drift.py`는 격리 컨테이너 한 개에 로컬·개발 모사 DB를 만든다. 같은 리비전으로 지정 테이블을 읽기 전용 수집했을 때 두 스냅샷은 동일했고 `MATCH`가 반환됐다. 개발 모사 DB의 `customer_id`를 제거한 뒤에는 `DRIFT`와 `REMOVED` 한 건이 반환됐다. 수집 단언 27건이 통과했고 컨테이너와 임시 파일을 정리했다. 검증 범위는 모사 DB와 선택 테이블의 정규화 컬럼이다. 실제 개발·운영 DB 검증은 미실행이다. [PostgreSQL 검증 증거](../../evidence/POSTGRESQL-SCHEMA-DRIFT-VALIDATION.json)

## ThingsBoard 장치 조회의 스키마 영향

고정된 ThingsBoard PR #14036의 변경 후 조회를 기준 fixture에서 성공시켜 JDBC 관측 지문과 등록 테스트 해시를 기존 PR 재현 결과와 대조했다. 같은 PostgreSQL 18 시험 컨테이너에 기준·누락·대조군 스키마를 격리했다. JDBC 메타데이터에서 실제 컬럼 타입과 길이를 수집한다. 이 파일럿에서 PostgreSQL의 `uuid`는 정규화 타입 `UUID`, 길이 0으로 전달한다. 쿼리가 참조하는 다섯 컬럼은 검토된 v2 매니페스트에 기록한다. [PR 재현 결과](../../evidence/THINGSBOARD-DEVICE-DAO-FOLLOWUP-VALIDATION.json)

```bash
python3 -B tools/thingsboard-pilot/run-device-schema-impact.py
```

| 실제 변경 | 영향 선정 및 재현 |
|---|---|
| `device.customer_id` 제거 | 등록 테스트 1건 선정. 선정 후 스키마 해시를 일치시켜 동일 조회를 재실행했고 PostgreSQL의 컬럼 누락 SQLSTATE `42703`을 확인했다. |
| 미사용 `device.fixture_note`를 `VARCHAR(16)`에서 `VARCHAR(32)`로 변경 | 선정 0건. 동일 조회 결과가 기준과 일치하고 관측 지문이 같았다. |

두 영향 보고서가 `COMPLETE`였고 시험 컨테이너와 임시 폴더를 정리했다. 누락 비교에는 같은 앱 리비전의 정상 조회 관측을 사용했고, 실제 누락 오류는 별도로 재현했다. 검증 범위는 고정 조회 한 건과 격리 스키마다. 전체 앱 실행과 운영 적용은 미실행이다. [장치 스키마 영향 증거](../../evidence/THINGSBOARD-DEVICE-SCHEMA-IMPACT-VALIDATION.json)

## 독립 주문 서비스의 스키마 영향 검증

검증된 독립 주문 파일럿 체크아웃을 재사용한다. 보호 실행기는 소스와 의존성 해시를 대조하고 기존 애플리케이션을 컴파일한 뒤 격리된 합성 fixture로 H2를 실행한다. 스키마 메타데이터와 실행 인벤토리를 수집하고 검토된 지문을 기준으로 버전 2 의존성 매니페스트를 생성한다. 매니페스트는 `requireActiveStock=false`인 주문 경로와 별도의 JDBC 감사 건수 조회 테스트를 대상으로 한다. JDBC 주문 항목에는 공유 래퍼를 거친 주문·재고 SQL의 의존성도 포함된다.

```bash
python3 -B tools/run-order-schema-impact.py --pilot-root ../udak-legacy-order-service-test
```

| 관측된 스키마 변경 | 영향받는 테스트 |
|---|---|
| `order_audit.event_code`를 `VARCHAR(16)`에서 `VARCHAR(32)`로 확대 | JDBC 감사 기록에 연결된 주문 등록. 감사 건수 조회 테스트의 참조는 주문 ID다. |
| `order_audit.fixture_note`를 `VARCHAR(16)`에서 `VARCHAR(32)`로 확대 | 0건. 같은 테이블의 미사용 시험용 컬럼을 대조군으로 사용한다. |

두 비교에 미해결 쿼리가 없었고 모두 `COMPLETE`였다. 수집에서 21개 단언을 통과했다. 선정 테스트는 비교 스키마와 메타데이터 해시가 일치하는 새로운 H2 fixture에서 재실행해 스키마 검사, 커밋, 롤백을 포함한 26개 단언을 통과했다. 스키마 해시가 다르면 재실행 전에 거부했다. 스키마 영향 계약 17건과 보호 Core 스모크도 통과했다. 외부 DB 연동은 NOT RUN이다. [주문 스키마 영향 증거](../../evidence/ORDER-SCHEMA-IMPACT-VALIDATION.json)

## 정적 SQL에서 컬럼 의존성 추출

Python 3로 `tools/sql-dependencies.py --schema <SCHEMA-SNAPSHOT.json 상대 경로>`를 실행하고 UTF-8 표준 입력으로 최대 16 KiB의 정적 SQL 문장 한 개를 전달한다. 추출기는 한정자 없는 단순 식별자를 사용하는 `SELECT COUNT(column) FROM table`과 `INSERT INTO table (columns) VALUES (?, ...)`를 지원한다. 추출한 모든 컬럼이 입력 스키마에 있는지 확인한다. 단일 테이블의 재고 UPDATE도 지원한다. `SET target = source - ?`에 `WHERE key1 = ? AND key2 = ? AND amount >= ?`가 이어지고 `AND flag = TRUE`가 선택적으로 붙는 형태다. 대입식 양쪽과 모든 조건의 컬럼을 스키마에서 확인한다.

JSON 보고서에는 `status`, `reason`, 정렬된 테이블·컬럼 참조만 포함한다. 종료 코드 `0`은 `RESOLVED`다. 종료 코드 `2`는 `UNRESOLVED`이며, 스키마에 없는 참조는 `UNKNOWN_REFERENCE`, 동적 SQL 표식은 `DYNAMIC_SQL`, 조인이나 모호한 참조 등 미지원 구문은 `UNSUPPORTED_SQL`로 표시한다. 잘못된 입력, 인자 또는 스키마는 종료 코드 `1`과 공통 오류 메시지를 반환한다.

```bash
python3 -B tools/run-order-schema-impact.py --dependency-extraction
```

고정 주문 fixture는 감사 건수 조회와 감사 기록 삽입의 정적 선언 두 개에서 추출한 참조가 검토된 매니페스트와 정확히 일치하는지 확인한다. 자동 추출만으로는 프레임워크·쿼리 항목 네 개 중 감사 건수 조회 한 개를 완전히 다룬다. 나머지 세 항목은 미해결로 남아 영향 보고서는 `INCOMPLETE`다. 검토된 상위 프레임워크의 명시적 참조와 추출한 감사 기록 삽입 의존성을 합치면 관련 컬럼 `event_code` 변경에서 주문 등록 테스트 한 건을 선택하고, 미사용 컬럼 `fixture_note` 변경에서는 0건을 선택한다. 보호 실행에서 추출 계약 9건, 스키마 영향 계약 17건, 선정 주문 재실행 단언 26개를 통과했다. 외부 DB 연동은 NOT RUN이다. [주문 의존성 추출 증거](../../evidence/ORDER-DEPENDENCY-EXTRACTION-VALIDATION.json)

## 렌더링된 주문 재고 UPDATE 의존성 검증

```bash
python3 -B tools/run-order-schema-impact.py --stock-update
```

| MyBatis 재고 경로 | 검토한 `order_stock` 컬럼 참조 |
|---|---|
| 활성 재고 조건 OFF | `available`, `sku_id`, `warehouse_id` |
| 활성 재고 조건 ON | `active`, `available`, `sku_id`, `warehouse_id` |

MyBatis가 준비한 문장을 각 관측 범위에서 검토된 참조와 대조한다. 원본 동적 매퍼 템플릿과 모호한 UPDATE는 미해결로 남는다. `active`의 NULL 허용 변경은 ON 테스트만 선정한다. 미사용 `fixture_note`의 길이 변경은 0건을 선정한다. ON 의존성을 빠뜨리면 비교 결과는 `INCOMPLETE`다. 선정 테스트는 메타데이터가 일치하는 새 H2 환경에서 재실행해 커밋·롤백·비활성 재고 거부를 검증한다. 외부 DB 연동은 NOT RUN이다. [주문 재고 UPDATE 검증 증거](../../evidence/ORDER-STOCK-UPDATE-VALIDATION.json)

## 관측된 스키마 변경과 마이그레이션 이력 대조

NEXT-004는 버전 1 스키마 스냅샷, 제출된 마이그레이션 이력, 검토한 마이그레이션 매니페스트를 별도 읽기 전용 명령으로 대조한다. 저장소 루트에서 크기가 제한된 로컬 JSON을 입력으로 실행한다.

```bash
python3 -B tools/schema-migration.py \
  --base build/schema/base/SCHEMA-SNAPSHOT.json \
  --head build/schema/head/SCHEMA-SNAPSHOT.json \
  --base-history build/schema/base/MIGRATION-HISTORY.json \
  --head-history build/schema/head/MIGRATION-HISTORY.json \
  --manifest build/schema/head/MIGRATION-MANIFEST.json
```

이력 파일에는 `schema_version`(정수 `1`), `revision`, `scope`, 적용 순서대로 정렬한 `migrations` 배열을 입력한다. 각 행에는 고유한 버전 문자열 `version`과 `checksum_sha256`이 들어간다. 매니페스트의 필드는 `schema_version`, `base_revision`, `revision`(head), `scope`, `version`, `checksum_sha256`, `expected_changes_sha256`이다. 다섯 입력의 범위가 정확히 일치해야 하며, 서로 다른 base와 head 리비전도 대응하는 값끼리 일치해야 한다.

head 이력의 앞부분은 base 이력과 적용 순서까지 정확히 일치해야 한다. head에 추가된 버전은 하나여야 하며, 해당 행의 버전과 체크섬은 매니페스트의 버전 및 검토한 마이그레이션 파일 바이트의 SHA-256과 각각 일치해야 한다. `expected_changes_sha256`은 검토한 변경 배열을 `schema.compare_columns`와 같은 순서와 구조로 작성하고 `json.dumps(changes, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")`로 인코딩한 뒤 계산한다.

종료 코드 `0`은 `MATCHED`, `2`는 `UNRESOLVED`다. 이력이 누락되거나 갈라진 경우, 스키마 변경이 비어 있거나 검토한 변경과 다른 경우는 `UNRESOLVED`다. 잘못된 인수, 입력 또는 범위는 `1`을 반환한다. CLI는 제출된 파일을 대조한다. Flyway 수집기는 별도로 이력 입력을 만든다.

주문 실행기는 격리된 H2 fixture에서 V002를 적용해 `order_audit.event_code`를 `VARCHAR(16)`에서 `VARCHAR(32)`로 확대한다. JDBC로 fixture 이력을 수집하고, 검토한 변경에 이력이 있는 경우와 빠진 경우, V002를 기록한 후 감사 코드 너비를 복원하고 무관한 변경이 생긴 경우를 확인한다. 세 경우에서 각각 `MATCHED`, `HISTORY_MISSING`, `CHANGE_MISMATCH`를 확인했다. [주문 마이그레이션 이력 증거](../../evidence/ORDER-MIGRATION-HISTORY-VALIDATION.json)

```bash
python3 -B tools/run-order-schema-impact.py --pilot-root ../udak-legacy-order-service-test --migration-history
```

### PostgreSQL 이력 대조 검증

```bash
python3 -B tools/run-postgresql-schema-migration.py
```

격리 PostgreSQL 18에서 검토한 V002 SQL 파일의 바이트를 고정 SHA-256과 대조한 뒤 적용했다. 기존 스키마 수집기로 `device.customer_id` 제거를 관측하고, 별도 시험용 테이블에 기록된 버전과 체크섬을 적용 순서대로 수집했다. 적용 전후에는 서로 다른 리비전과 같은 논리 테이블 범위를 사용했다. 스키마와 이력 수집은 읽기 전용 트랜잭션에서 수행했다.

| 관측 스키마와 이력 | 대조 결과 |
|---|---|
| 컬럼 제거, 버전·체크섬 일치 | `MATCHED` · 종료 코드 0 |
| 같은 컬럼 제거, 새 이력 누락 | `UNRESOLVED` · `HISTORY_MISSING` |
| 같은 컬럼 제거, 기록 버전 불일치 | `UNRESOLVED` · `VERSION_MISMATCH` |
| 같은 컬럼 제거, 적용 파일 체크섬 불일치 | `UNRESOLVED` · `CHECKSUM_MISMATCH` |
| 버전·체크섬 일치, 미사용 컬럼 폭 변경 추가 | `UNRESOLVED` · `CHANGE_MISMATCH` |

PostgreSQL fixture 단언 41건과 시험 자원 정리를 확인했다. 이 실행의 이력은 직접 관리한 시험 테이블에서 수집했다. [PostgreSQL 이력 대조 증거](../../evidence/POSTGRESQL-SCHEMA-MIGRATION-VALIDATION.json)

### 실제 Flyway 이력 수집

```bash
python3 -B tools/run-flyway-schema-history.py
```

격리 PostgreSQL 18에서 Flyway OSS 11.20.3으로 검토된 V002를 적용했다. 보호 실행기는 승인된 파일을 전용 경로에 복사하고 적용 전후 바이트의 SHA-256을 확인한다. `FlywayHistoryCollector.collect`는 호출자의 읽기 전용 트랜잭션에서 지정 스키마의 기본 `flyway_schema_history`를 읽는다. 성공한 정수 버전 SQL 한 건의 적용 순번·버전·스크립트·Flyway 체크섬을 신뢰할 수 있는 적용 당시 증거와 대조한다. 현재 검토 파일의 바이트도 적용 당시 SHA-256과 일치해야 v1 이력을 내보낸다. 파일 근거를 확인하지 못하면 `HISTORY_FILE_UNVERIFIED`를 반환하고 비교 입력 생성을 차단한다. [Flyway 검증 방식](https://github.com/flyway/flyway/blob/main/documentation/Reference/Commands/Validate.md)

| 격리 PostgreSQL의 사례 | 결과 |
|---|---|
| 실제 V002 적용, 검토 파일과 적용 당시 증거 일치 | v1 이력 1건 내보내기 · `MATCHED` 경로 통과 |
| 같은 컬럼 제거, Flyway 이력 없음 | 빈 이력 내보내기 · `UNRESOLVED` / `HISTORY_MISSING` |
| 성공 이력과 검토 파일은 있으나 적용 당시 증거 없음 | `HISTORY_FILE_UNVERIFIED` · 입력 생성 차단 |
| 줄바꿈 변경으로 Flyway CRC32는 같고 파일 SHA-256은 다름 | Flyway 검증 통과 · UDAK 입력 생성 차단 |

Flyway 런타임 의존성은 이 보호 검증에서만 사용한다. 단일 SQL 이력 검증의 단언 23건이 통과했고 시험 자원을 정리했다. 복수 이력, Liquibase, 실제 개발·운영 환경은 미실행이다. [Flyway 이력 검증 증거](../../evidence/POSTGRESQL-FLYWAY-HISTORY-VALIDATION.json)

## 고정 fixture 회귀 재현

Python 3, JDK 17 이상, Maven Central 접근과 macOS에서 기존에 설치한 네이티브 arm64 Homebrew PostgreSQL 17 및 MySQL 8.0 바이너리가 필요하다. 실행기는 별도 임시 인스턴스와 전용 fixture를 초기화하고 DB를 한 번에 하나씩 기동한다. 기존 정지 컨테이너 12개를 보존하며 새 컨테이너 생성은 0개다. [PostgreSQL 17 초기화](https://www.postgresql.org/docs/17/app-initdb.html) · [MySQL 8.0 초기화](https://dev.mysql.com/doc/refman/8.0/en/data-directory-initialization.html)

```bash
python3 tools/run-schema-regression.py
```

실행기는 PostgreSQL JDBC 42.7.14와 checker-qual 3.55.1, MySQL Connector/J 26.10.0과 protobuf-java 4.36.1을 고정한다. 엔진별로 fixture를 만들고 head 쪽의 NULL 허용 `label`을 `VARCHAR(32)`에서 `VARCHAR(64)`로 늘린다. JDBC 메타데이터로 만든 스냅샷을 바탕으로 엔진별 영향 대상 쿼리 두 개를 선택한다. 바인딩한 ID로 조회하는 쿼리와 정렬된 목록 조회 쿼리다. ID만 정렬 조회하는 쿼리는 영향 대상 선택을 확인하는 데 사용한다. base와 head 결과를 서로 비교하고 별도로 정의한 기대 행과 대조해 컬럼 라벨, SQL 및 Java 타입, NULL 처리, 정렬, 빈 조회 결과를 확인한다.

회귀 범위는 이 쿼리와 엔진의 네 조합이다. SQL Server, Oracle, 운영 스키마, 성능·부하 테스트는 **NOT RUN**이다. G0 승인은 대기 상태다. 확장 Phase 4는 제한된 범위에서 DB/드라이버 취소·복구와 커넥션 재사용, 트랜잭션 결과를 검증한다. [확장 로드맵](09-WBS-ROADMAP.md)

## 실제 검증 결과

| 실제 DB | 사용한 JDBC | 실행 결과 |
|---|---|---|
| PostgreSQL 17.11 | PostgreSQL JDBC 42.7.14 | 선택 쿼리 2개·단언 98개 PASS |
| MySQL 8.0.46 | MySQL Connector/J 26.10.0 | 선택 쿼리 2개·단언 98개 PASS |

두 엔진에서 같은 스키마 변경과 테스트 ID가 선택됐고 쿼리별 결과 해시가 일치했다. 영향 분석 계약 검사 17개, Inventory 단언 48개, Core smoke를 통과했다. 실행기는 네이티브 서버를 순차 기동하며 기존 컨테이너의 데이터를 사용하지 않는다. 네이티브 바이너리의 버전·해시와 JDBC에서 확인한 서버·드라이버 식별값을 기록했다. [실행 증거](../../evidence/SCHEMA-REGRESSION-VALIDATION.json)

실DB 실행 후 소유 프로세스 그룹이 종료됐고 임시 파일 1,188개·149,563,199바이트를 정리했다. 별도 실패·중단 검사에서도 소유한 PostgreSQL 서버가 종료됐고 두 경우 모두 임시 파일이 남지 않았다. 기존 관리형 컨테이너 12개의 ID와 정지 상태를 대조했다. [정리 및 저장소 검사](../../evidence/SCHEMA-REPOSITORY-VALIDATION.json)
