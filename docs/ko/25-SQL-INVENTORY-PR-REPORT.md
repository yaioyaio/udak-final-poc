# SQL 인벤토리와 PR 보고서

[English](../en/25-SQL-INVENTORY-PR-REPORT.md) | 한국어

## 범위

확장 Phase 1은 `INV-001`, `INV-002`, `INV-003`을 구현한다. JDK 전용 `dev.udak.inventory.InventoryCapture`를 Hibernate, MyBatis, JdbcTemplate의 기존 `ObservationSink`로 연결한다. 어댑터는 기존 Observe 및 정규화 경로를 사용한다. 인벤토리는 SQL 형태 fingerprint와 관측 지점 등 메타데이터를 기록한다. SQL 원문, 바인드 값, 접속정보는 수집 대상에서 제외한다. 쿼리·테스트 ID는 코드에서 관리하며 민감정보를 포함하지 않는다.

이미 알려진 쿼리는 정의 목록에 명시적으로 등록한다. 런타임 관측은 테스트 시나리오가 도달한 수집 지점을 보여 준다. 관측 횟수는 동일 지점의 반복 관측도 포함하며 실행 성공이나 커밋을 판정하는 근거로 사용할 수 없다. 정의 목록의 범위는 명시적으로 등록한 항목까지다. 범용 정적 소스 스캔은 이 단계의 범위에서 제외한다.

## 수집 및 내보내기

리비전과 시나리오별로 수집기를 하나 만든다. 해당 observer를 Hibernate statement inspector, MyBatis interceptor, JDBC DataSource wrapper에 전달한다. 어댑터 등록 위치는 기존 연결 예시를 참조한다. [Legacy Observe 연결](21-LEGACY-OBSERVE-RESULTS.md)

```java
import dev.udak.inventory.InventoryCapture;
import dev.udak.observe.Framework;
import dev.udak.observe.SqlObserver;

var capture = new InventoryCapture();
var observer = new SqlObserver(capture);
capture.declare(Framework.MYBATIS, "Order.findOpen", "Order.findOpen.contract");

try (var scope = capture.scope("Order.findOpen", "Order.findOpen.contract")) {
    // 이 스레드에서 테스트할 쿼리를 실행한다.
}

String snapshot = capture.snapshotJsonWithObservedTests(revision, profile);
```

형태 fingerprint가 바뀌어도 같은 쿼리로 찾아갈 수 있도록 base와 head에서 동일한 논리 쿼리 ID를 사용한다. 스코프는 스레드 로컬이므로 쿼리를 실행하는 스레드에서 설정한다. 대체 `OBSERVE_ID`는 개별 관측을 식별하며 fingerprint 변경 전후를 연결하는 논리 키로는 적합하지 않다. 스냅샷에는 ID 해시를 저장한다. 로컬 코드에서 스코프로 지정한 쿼리나 테스트의 참조를 대조하려면 `InventoryCapture.hashQueryId` 또는 `InventoryCapture.hashTestId`를 사용한다.

시나리오가 끝나고 참여 스레드의 작업이 모두 멈춘 뒤 내보낸다. 애플리케이션이 반환된 JSON을 `build/inventory/base/SQL-INVENTORY.json` 또는 `build/inventory/head/SQL-INVENTORY.json`에 직접 기록한다. `revision`에는 40자 또는 64자의 전체 Git 커밋 ID를 소문자 16진수로 지정한다. 두 수집의 `profile`에는 코드에서 관리하는 시나리오 및 환경 식별자의 동일한 SHA-256 다이제스트를 64자의 소문자 16진수로 지정한다. 내보낸 스냅샷은 Git에서 제외하는 `build/` 아래에 둔다.

실제로 관측한 테스트 연결이 필요한 경우 `snapshotJsonWithObservedTests(revision, profile)`로 v2 인벤토리를 내보낸다. `shapes[]`의 각 항목에는 지문, 구문 종류, 정렬하고 중복을 제거한 `test_ids` 배열이 들어간다. 실행 스레드에 테스트 스코프가 있고 정규화된 관측을 수집했을 때만 연결을 기록한다. 선언, 정규화 불가, 테스트 스코프가 없는 관측에서는 지문에 테스트를 연결하지 않는다. 쿼리 단위 `test_ids`에는 계속 등록된 테스트 참조가 포함된다. 기존 `snapshotJson`은 v1을 내보낸다.

PR CLI는 v1, v2 및 혼합 버전 쌍을 읽는다. SQL 형태를 비교하고 완전한 v2 스냅샷 두 개에서는 지문별 관측 테스트 연결도 보고한다. 스키마 영향의 테스트 연결을 검증할 때는 v2 인벤토리와 v2 의존성 매니페스트를 사용한다. [스키마 영향 검증](27-SCHEMA-IMPACT-REGRESSION.md#지문을-관측한-테스트-연결-검증)

## PR 보고서 생성

```bash
python3 tools/sql-inventory.py --base build/inventory/base/SQL-INVENTORY.json --head build/inventory/head/SQL-INVENTORY.json --format markdown
```

읽기 전용 CLI는 표준 출력으로 결과를 보낸다. 기본 형식은 JSON이다. PR 검토에 파일이 필요하면 Markdown 출력을 `build/`의 파일로 리디렉션한다.

| 종료 코드 | 의미 |
|---|---|
| 0 | 비교 가능. 변경사항이 있을 수 있다. |
| 1 | 프로필 불일치를 포함한 잘못된 입력 또는 사용법 오류. |
| 2 | 관측 불가 또는 누락된 사건으로 비교 불완전. |
| 3 | 비교 가능한 변경사항이 있으며 `--fail-on-change`가 지정됨. |

보고서에서 관측된 fingerprint의 변경, 관측 커버리지, 관련 테스트 참조를 검토한다. head 스냅샷에 항목이 없어졌다면 테스트 커버리지 변화일 수 있다. 소스에서 확인한 뒤 삭제 여부를 판단한다. 수집 상한은 항목 128개이며 항목별 테스트 참조와 형태는 각각 8개다. 누락되었거나 사용할 수 없는 증거가 있으면 비교는 불완전하다.

## PR에서 지문별 관측 테스트 연결 검토

완전한 v2 스냅샷 두 개를 비교하면 같은 프레임워크, 스코프의 Query ID, 지문에서 관측된 테스트의 추가·삭제가 표시된다. JSON의 `queries[].fingerprint_test_changes`에 `gained_test_ids`와 `lost_test_ids`가 나타난다. Markdown은 각 지문 아래에 해당 해시를 표시한다. 연결 삭제는 head 관측에 해당 연결이 나타나지 않았다는 뜻이다. 테스트 연결만 변하면 SQL 형태는 `UNCHANGED`로 유지되고 영향 테스트에는 변경된 연결의 테스트만 포함된다. `--fail-on-change`를 지정하면 비교 가능한 연결 변경은 종료 코드 3을 반환한다.

`fingerprint_test_status`는 완전한 v2 쌍에서 `COMPARABLE`, v1·v2 혼합 비교에서 `MIXED_VERSIONS`, v2 쌍에 누락 또는 정규화 불가 관측이 있으면 `INCOMPLETE`다. 혼합 버전과 불완전 쌍에서는 기존 쿼리·SQL 형태 비교를 계속 제공하고 지문별 연결 변화는 생략한다. v1 스냅샷 두 개는 기존 보고서 형식을 사용한다.

```bash
python3 -B tools/run-sql-inventory.py --fingerprint-test-links
```

보호 H2 검증은 같은 Query ID에서 두 JDBC SQL 형태를 두 스냅샷에 동일하게 실행한다. 관측 테스트 연결을 교환하면 JSON과 Markdown에서 추가 2건, 삭제 2건을 표시한다. 두 SQL 형태는 `UNCHANGED`다. 혼합 버전과 불완전 대조군에서는 연결 변화가 표시되지 않는다. [PR 지문별 테스트 변경 검증 증거](../../evidence/INVENTORY-FINGERPRINT-TEST-CHANGES-VALIDATION.json)

## 영향 테스트 해시를 주문 회귀 테스트에 연결

`tools/sql-inventory.py`가 생성한 런타임 JSON 보고서를 `SQL-INVENTORY-REPORT.json`으로 저장하고 저장소 상대 경로를 전달한다. 대조 명령은 최대 1 MiB의 로컬 파일과 런타임 보고서 스키마 v1을 지원한다. 선택형 Mapper XML 보고서를 병합하기 전의 런타임 보고서를 사용한다.

```bash
python3 -B tools/order-pr-regression.py --report build/inventory/SQL-INVENTORY-REPORT.json
```

주문 파일럿은 테스트 ID 세 개와 각각의 고정 보호 진입점을 등록한다. 대조에는 인벤토리의 테스트 ID 해시를 사용한다.

| 등록 테스트 ID | 진입점 |
|---|---|
| `case.order.place` | `ORDER_PLACEMENT_RELATED` |
| `case.order.stock-off` | `ORDER_STOCK_OFF_RELATED` |
| `case.order.stock-on` | `ORDER_STOCK_ON_RELATED` |

완전한 보고서에서 영향 테스트가 모두 등록됐으면 `READY`, 영향 테스트가 없으면 `NO_IMPACT`다. 두 상태는 종료 코드 0을 반환한다. 미등록 해시, 불완전 보고서, 혼합 버전은 `REVIEW_REQUIRED`와 종료 코드 2를 반환한다. 해당 사유인 `UNKNOWN_TEST_HASH`, `INCOMPLETE_REPORT`, `MIXED_INVENTORY_VERSIONS`를 표시하고 등록된 매칭 결과와 미등록 해시를 함께 유지한다. 잘못됐거나 일관성이 없는 입력의 종료 코드는 1이다. 대조 명령은 읽기 전용이다. 보호 실행은 주문 파일럿 하네스가 맡는다.

```bash
python3 -B tools/run-order-schema-impact.py --pr-regression
```

하네스는 H2에서 관측한 재고 분기를 빈 인벤토리 대조군과 비교한다. `READY`인 PR 보고서 한 건에 OFF·ON 테스트의 서로 다른 해시가 표시된다. 각 보호 진입점은 새 H2 환경의 관련 스키마 해시를 확인한 뒤 애플리케이션을 실행한다. OFF는 비활성 재고 주문의 커밋과 롤백을 검증한다. ON은 커밋·롤백과 비활성 재고 거부를 검증한다. 두 진입점 모두 미사용 컬럼을 변경한 대조 스키마의 해시를 거부한다. 합성 미등록 해시, 혼합 버전, 관측 누락 대조군은 검토가 필요하다. [주문 재고 OFF·ON 재실행 증거](../../evidence/ORDER-STOCK-PR-REPLAY-VALIDATION.json)

## 선택형 Mapper XML 검토 (NEXT-002)

같은 base와 head 리비전의 인벤토리 스냅샷과 로컬 Mapper XML 파일을 준비한다. 아래 선택형 명령은 기존 인벤토리 보고서에 Mapper XML 섹션을 추가한다.

```bash
python3 -B tools/sql-inventory-mapper.py \
  --base build/inventory/base/SQL-INVENTORY.json \
  --head build/inventory/head/SQL-INVENTORY.json \
  --base-mappers build/inventory/base/ExampleMapper.xml \
  --head-mappers build/inventory/head/ExampleMapper.xml \
  --format markdown
```

두 파일 목록 옵션을 명시하고 전체에서 파일을 하나 이상 선택한다. 빈 목록은 해당 리비전에서 선택한 Mapper XML이 없음을 뜻한다. 일반 XML 파일의 명시적 상대 경로를 지정한다. JSON은 기존 관측 필드 옆에 `mapper_xml`을 제공한다. Mapper 섹션은 추가·내용 변경·삭제 및 정적 발견을 파일·줄·분류·해시로 기록한다. 내부에서는 namespace, 문장 ID와 database ID로 선언을 대응시킨다. 파일과 줄을 제외하고 속성과 텍스트를 포함한 파싱 결과를 해시하므로 선언의 줄 이동만으로는 변경을 기록하지 않는다.

동적 치환 발견은 검토할 SQL 텍스트와 CDATA 위치를 제공한다. 스캐너의 범위는 선택한 XML 선언이며 템플릿 표현식을 평가하지 않는다. include, 중첩 키 쿼리, 커스텀 스크립팅 언어, 미지원 요소와 모호한 식별자는 Mapper 비교를 불완전하게 만들 수 있다. 불완전하면 종료 코드 `2`가 우선하며, 비교가 완전하고 변경이 있는 경우 `--fail-on-change`에서 `3`을 반환한다. 입력 거부는 `1`이다.

파서는 표준 MyBatis Mapper DTD 선언을 표시로 받아들인다. 외부 해석을 비활성화하고 선택한 로컬 파일만 사용한다. 상한은 리비전별 Mapper 파일 32개, XML 파일당 1 MiB, 양쪽 XML 파싱 합계 4 MiB, XML 중첩 32단계를 포함한다. [Mapper XML 참고](https://mybatis.org/mybatis-3/sqlmap-xml.html) · [스캐너 소스](../../tools/sql-inventory-mapper.py)

오프라인 회귀는 `python3 -B tools/test-sql-inventory-mapper.py`로 실행한다. 2026-11-22에 Mapper 테스트 9건, 기존 인벤토리 CLI 12건, 별도 프로세스의 CLI 스모크와 보호 Core 스모크가 통과했다. 보존한 인벤토리 통합 증거는 이전 Core 입력 해시에 묶여 있다. 현재 리비전의 DB 통합 검증은 NOT RUN이다. [검증 상태](16-TRACEABILITY.md#기능-우선-검증)

## 로컬 검증

```bash
python3 tools/run-sql-inventory.py
```

제한된 실행기는 인벤토리 및 PR 보고서 계약과 기존 Core smoke, 실제 레거시 H2 테스트를 실행한다. [추적성과 검증 상태](16-TRACEABILITY.md)

## 실제 검증과 차기 작업

보호 실행 13단계를 통과했다. 수집기 단언 48개, 통합 단언 14개, CLI 검사 12개, Core smoke, 기존 H2 호환성 시나리오 10개를 확인했다. H2에서 Hibernate·MyBatis·JdbcTemplate을 실제 호출해 두 스냅샷을 얻고 합성 리비전 ID를 사용했다. 보고서는 MyBatis SQL 형태 변경 1건, JDBC 신규 관측 1건, 영향 테스트 참조 2개를 식별했다. 잘못된 입력과 불완전 수집도 검증했다. 임시 파일 123개·38,017,839바이트를 정리했으며 실행 임시 파일 잔여는 0개다. [실행 증거와 예시 보고서](../../evidence/SQL-INVENTORY-VALIDATION.json)

JDK 전용 모듈과 H2 통합 코드를 Java 17 대상으로 컴파일했다. 독립 Gradle 빌드와 4종 실DB 재실행은 NOT RUN이다. 다음은 확장 Phase 2의 트랜잭션 경계 추적이다. 메타데이터로 SQL 관측과 Spring 트랜잭션 참여·결과를 연결하고 실제 프레임워크 호출로 검증한다. [로드맵](09-WBS-ROADMAP.md#제품-확장-단계)

## 관측 불가 사유별 집계

`InventoryCapture`는 SQL 형태 정규화가 실패하면 고정 사유 코드를 인벤토리 항목별로 집계한다. JSON·Markdown 보고서는 쿼리별과 비교 기준·대상별 건수를 보여 준다. 사유를 담지 않은 기존 스냅샷과 1인자 sink 입력의 건수는 `UNSPECIFIED`로 집계한다. 사유 집계 대상은 수락된 관측 불가 이벤트다. 누락 건수는 별도로 기록하며 관측 불가 또는 누락이 있으면 보고서는 계속 `INCOMPLETE`다.

스키마 버전 1의 선택 필드 `unavailable_reasons`에는 `EMPTY_SQL`, `SQL_TOO_LONG`, `MULTIPLE_STATEMENTS`, `AMBIGUOUS_SYNTAX`, `UNSUPPORTED_SYNTAX`, `MALFORMED_SYNTAX`, `LEXER_LIMIT`, `UNSPECIFIED`만 허용한다. 양의 건수 합계는 항목의 `unavailable`과 일치한다. 관측 이벤트·지문·기존 1인자 sink API 계약은 유지된다. 사유를 직접 받으려면 2인자 sink 콜백을 사용한다.

## MyBatis와 JDBC에 관측된 형태 변경 검토

두 관측이 조건을 충족하면 JSON에 `shared_shape_changes`가 추가된다. 논리 쿼리 해시, 기준·대상 형태, 공통 테스트 해시와 두 관측 지점을 표시한다. Markdown은 검토 후보 한 건 아래에 `MYBATIS_PREPARE`와 `JDBC_EXECUTE`의 근거를 각각 표시한다. 두 형식 모두 프레임워크별 근거를 보존하며 기존 비교 상태와 종료 코드를 적용한다.

동일한 `SCOPED` 쿼리 해시, 양쪽에서 동일하게 빠진 형태 하나와 추가된 형태 하나, 두 형태의 동일한 문장 유형, 기준·대상의 두 관측 항목 모두에 존재하는 공통 테스트 참조가 필요하다. 두 관측 항목의 지문이 사용 가능하고 두 스냅샷의 누락 건수가 0이어야 한다. 한 프레임워크에만 변경 없는 형태가 더 있어도 된다. 각 관측 지점은 수집한 관측 근거를 나타낸다. 실제 실행 횟수와 결과는 업무 테스트로 확인한다.

독립 H2 주문 회귀에서 재고 SQL 변경 한 건과 관측 지점 두 개를 확인했다. 바인딩 값 대조군과 관측 공백 대조군에는 묶음이 없었다. [검증 증거](../../evidence/INVENTORY-SHARED-OBSERVATION-VALIDATION.json)
