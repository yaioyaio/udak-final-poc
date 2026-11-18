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

String snapshot = capture.snapshotJson(revision, profile);
```

형태 fingerprint가 바뀌어도 같은 쿼리로 찾아갈 수 있도록 base와 head에서 동일한 논리 쿼리 ID를 사용한다. 스코프는 스레드 로컬이므로 쿼리를 실행하는 스레드에서 설정한다. 대체 `OBSERVE_ID`는 개별 관측을 식별하며 fingerprint 변경 전후를 연결하는 논리 키로는 적합하지 않다. 스냅샷에는 ID 해시를 저장한다. 로컬 코드에서 스코프로 지정한 쿼리나 테스트의 참조를 대조하려면 `InventoryCapture.hashQueryId` 또는 `InventoryCapture.hashTestId`를 사용한다.

시나리오가 끝나고 참여 스레드의 작업이 모두 멈춘 뒤 내보낸다. 애플리케이션이 반환된 JSON을 `build/inventory/base/SQL-INVENTORY.json` 또는 `build/inventory/head/SQL-INVENTORY.json`에 직접 기록한다. `revision`에는 40자 또는 64자의 전체 Git 커밋 ID를 소문자 16진수로 지정한다. 두 수집의 `profile`에는 코드에서 관리하는 시나리오 및 환경 식별자의 동일한 SHA-256 다이제스트를 64자의 소문자 16진수로 지정한다. 내보낸 스냅샷은 Git에서 제외하는 `build/` 아래에 둔다.

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

## 로컬 검증

```bash
python3 tools/run-sql-inventory.py
```

제한된 실행기는 인벤토리 및 PR 보고서 계약과 기존 Core smoke, 실제 레거시 H2 테스트를 실행한다. [추적성과 검증 상태](16-TRACEABILITY.md)

## 실제 검증과 차기 작업

보호 실행 13단계를 통과했다. 수집기 단언 48개, 통합 단언 14개, CLI 검사 12개, Core smoke, 기존 H2 호환성 시나리오 10개를 확인했다. H2에서 Hibernate·MyBatis·JdbcTemplate을 실제 호출해 두 스냅샷을 얻고 합성 리비전 ID를 사용했다. 보고서는 MyBatis SQL 형태 변경 1건, JDBC 신규 관측 1건, 영향 테스트 참조 2개를 식별했다. 잘못된 입력과 불완전 수집도 검증했다. 임시 파일 123개·38,017,839바이트를 정리했으며 실행 임시 파일 잔여는 0개다. [실행 증거와 예시 보고서](../../evidence/SQL-INVENTORY-VALIDATION.json)

JDK 전용 모듈과 H2 통합 코드를 Java 17 대상으로 컴파일했다. 독립 Gradle 빌드와 4종 실DB 재실행은 NOT RUN이다. 다음은 확장 Phase 2의 트랜잭션 경계 추적이다. 메타데이터로 SQL 관측과 Spring 트랜잭션 참여·결과를 연결하고 실제 프레임워크 호출로 검증한다. [로드맵](09-WBS-ROADMAP.md#제품-확장-단계)
