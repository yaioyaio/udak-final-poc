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
| `QUERY-DEPENDENCIES.json` (head) | `schema_version` (정수 `1`), `revision`, `scope`, `dependencies`. 각 의존성에는 `framework` (`JPA`, `MYBATIS`, `JDBC` 중 하나), 인벤토리의 `query_id_hash`, `table`과 `column` 쌍으로 이루어진 `columns`가 들어간다. 해당 테이블의 모든 컬럼 변경을 포함하려면 `column`에 `*`를 쓴다. |

base와 head의 `revision`은 각각 40자 또는 64자의 소문자 16진수이며 서로 달라야 한다. 두 스냅샷과 매니페스트에는 64자의 소문자 16진수로 된 같은 `scope`를 쓴다. head 스냅샷, 인벤토리, 매니페스트는 같은 head `revision`을 쓴다. 인벤토리의 `profile`은 스키마의 `scope`와 같아야 한다. `query_id_hash`도 64자의 소문자 16진수다. 테이블·컬럼 식별자는 소문자로 시작하며 이후 소문자, 숫자, 밑줄을 포함해 최대 63자까지 허용한다. 정규화 타입은 `INTEGER`, `BIGINT`, `VARCHAR`, `DECIMAL`, `BOOLEAN`, `DATE`, `TIMESTAMP`, `TEXT`다. `VARCHAR`의 `width`는 1~100,000이고 나머지 타입은 0이다.

CLI는 POSIX에서 크기 제한이 있는 로컬 JSON 파일을 읽기 전용으로 처리한다. 입력은 심볼릭 링크가 없는 상대 경로에 있는 하드 링크 수 1, 최대 1 MiB의 일반 파일이어야 한다. 스냅샷당 최대 4,096개 컬럼, 매니페스트당 최대 128개 쿼리, 쿼리당 최대 128개 참조를 허용한다. CLI 입력은 정규화된 메타데이터로 한정한다. DDL·마이그레이션·저장소 소스 파싱은 구현 범위 밖이며 CLI는 SQL을 실행하지 않는다. [Phase 1 인벤토리 계약](25-SQL-INVENTORY-PR-REPORT.md)

| 종료 코드 | 의미 |
|---|---|
| `0` | `COMPLETE`. 스키마 변경, 영향받는 쿼리 해시, 중복을 제거한 테스트 해시 목록 `impacted_test_ids`를 제공한다. 변경 유형은 `ADDED`, `REMOVED`, `TYPE`, `WIDTH`, `NULLABILITY`다. |
| `1` | 잘못된 인수 또는 입력. |
| `2` | `INCOMPLETE`. 확인된 변경과 영향은 보고서에 포함한다. 변경이 있는데 인벤토리가 비어 있거나, 관측 누락, 관측 정보 미확보, 관측 전용 임시 ID, 테스트·의존성 누락, 확인되지 않은 쿼리·참조가 있으면 비교 결과를 불완전으로 표시한다. |


## 환경 간 스키마 계약 비교

NEXT-004는 기존 JDBC 연결에서 버전 1 정규화 컬럼 스냅샷을 수집한다. 최초 지원 DBMS는 H2이며 드라이버 2.3.232로 검증한다. JDBC 카탈로그와 스키마의 정확한 이름을 지정하고 고정 논리 테이블명을 정확한 물리 테이블명과 매핑한다. 두 환경에 같은 논리 테이블 목록을 사용한다. 수집기는 JDBC 컬럼 메타데이터를 읽고 호출자의 연결 및 연결 상태를 유지한다. [JDBC 컬럼 메타데이터](https://docs.oracle.com/en/java/javase/17/docs/api/java.sql/java/sql/DatabaseMetaData.html#getColumns(java.lang.String,java.lang.String,java.lang.String,java.lang.String))

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

종료 코드 `0`은 `MATCH`, `2`는 `DRIFT`, `1`은 입력 또는 범위 오류다. 컬럼의 추가·삭제·타입·VARCHAR 길이·NULL 허용 여부 변화를 표시한다. 지정 테이블이 없거나 접근할 수 없거나 컬럼 메타데이터가 미지원이면 수집을 실패 처리한다. 지정 테이블은 최대 128개, 컬럼은 최대 4,096개다. 수집기는 H2의 일반 대문자 또는 소문자 식별자를 소문자로 정규화하고 대소문자 혼합 컬럼명은 거부한다. 출력에는 논리 식별자와 컬럼 정의가 포함되므로 공유가 승인된 식별자를 사용한다. 키, 인덱스, 기본값, DECIMAL 정밀도·스케일, 마이그레이션 이력과 쿼리 의존성 자동 추출은 이 계약의 범위 밖이다.

`python3 tools/run-schema-drift.py`로 범위를 제한한 로컬 검증을 실행한다. 같은 리비전의 독립 H2 환경에서 변경 없는 스냅샷과 변경이 있는 스냅샷을 검증한다. 이 수집기의 외부 DBMS 검증은 NOT RUN이다. [NEXT-004 검증 증거](../../evidence/SCHEMA-DRIFT-VALIDATION.json)

## 독립 주문 서비스의 스키마 영향 검증

검증된 독립 주문 파일럿 체크아웃을 재사용한다. 보호 실행기는 소스와 의존성 해시를 대조하고 기존 애플리케이션을 컴파일한 뒤 격리된 합성 fixture로 H2를 실행한다. 스키마 메타데이터와 실행 인벤토리를 수집하고 버전 1 명시적 의존성 매니페스트를 생성한다. 매니페스트는 `requireActiveStock=false`인 주문 경로와 별도의 JDBC 감사 건수 조회 테스트를 대상으로 한다. JDBC 주문 항목에는 공유 래퍼를 거친 주문·재고 SQL의 의존성도 포함된다.

```bash
python3 -B tools/run-order-schema-impact.py --pilot-root ../udak-legacy-order-service-test
```

| 관측된 스키마 변경 | 영향받는 테스트 |
|---|---|
| `order_audit.event_code`를 `VARCHAR(16)`에서 `VARCHAR(32)`로 확대 | JDBC 감사 기록에 연결된 주문 등록. 감사 건수 조회 테스트의 참조는 주문 ID다. |
| `order_audit.fixture_note`를 `VARCHAR(16)`에서 `VARCHAR(32)`로 확대 | 0건. 같은 테이블의 미사용 시험용 컬럼을 대조군으로 사용한다. |

두 비교에 미해결 쿼리가 없었고 모두 `COMPLETE`였다. 수집에서 21개 단언을 통과했다. 선정 테스트는 비교 스키마와 메타데이터 해시가 일치하는 새로운 H2 fixture에서 재실행해 스키마 검사, 커밋, 롤백을 포함한 26개 단언을 통과했다. 스키마 해시가 다르면 재실행 전에 거부했다. 스키마 영향 계약 17건과 보호 Core 스모크도 통과했다. 외부 DB 연동은 NOT RUN이다. [주문 스키마 영향 증거](../../evidence/ORDER-SCHEMA-IMPACT-VALIDATION.json)

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
