# 제품 G5 인수 기준

[English](../en/32-PRODUCT-G5-ACCEPTANCE.md) | 한국어

PRD는 변환을 끈 Observe 경로의 p95 지연 시간 증가율을 기준 경로 대비 5% 이내로 제한하는 것을 목표로 한다(NFR-02, RELEASE-008). 커넥션 풀 동작은 별도 기능 시험으로 검증한다(RELEASE-009). [PRD](01-PRD.md) · [추적성](16-TRACEABILITY.md)

## Observe 성능 (RELEASE-008)

격리된 소규모 fixture에 고정된 매개변수화 `SELECT` 한 종류를 실행한다. 각 DB 프로파일의 두 경로에서 같은 버전으로 고정한 `JdbcTemplate`, 드라이버, SQL, 바인드 입력, 행 매핑, fixture, 커넥션 구성을 사용한다. 기준 경로는 `JdbcTemplate`을 직접 호출한다. Observe 경로는 SQL 변환을 끈 상태에서 이를 호출한다. 반환 행을 fixture의 기대값 및 두 경로 간에 대조한다.

기준 → Observe와 Observe → 기준의 쌍 순서를 번갈아 실행한다. DB 프로파일별로 각 경로에서 웜업 8건과 측정 96건을 완료한다. 단조 시계로 호출 진입부터 반환까지 잰다. fixture 준비, 시작 간격 대기와 웜업 표본은 p95 계산에서 제외한다. 각 경로에서 측정값 96개를 정렬해 92번째 값을 최근접 순위법으로 구한 p95로 나노초 단위로 기록한다. 프로파일마다 `100 × (Observe p95 − 기준 p95) / 기준 p95`를 계산한다.

두 경로의 호출·측정 표본이 모두 있고 기준 p95가 양수이며, 반올림 전 증가율이 5% 이내이고 실행 오류와 결과 불일치가 각각 0건일 때만 해당 프로파일이 통과한다. 측정값이 누락되면 통과할 수 없다. 프로파일별로 판정하고 이 범위의 통과에는 두 프로파일 모두 통과해야 한다. 소프트웨어 버전, 표본 수, p95, 오류, 불일치, 자원 한도와 정리 결과를 기록한다. 결론은 검증한 쿼리, fixture, 설정과 버전에 한정한다.

| 항목 | 승인한 1회 실행 |
|---|---|
| 프로파일 | 격리된 네이티브 PostgreSQL 17.11 / JDBC 42.7.14 및 MySQL 8.0.46 / Connector/J 26.10.0. 루프백에서 DB를 하나씩 실행한다. |
| SQL 작업 | 웜업을 포함해 DB별 작업 시작은 정확히 208건이다. 동시 진행은 최대 1건, 임의의 연속 1초당 시작은 최대 8건, 시작 간격은 최소 125 ms다. |
| 시간과 자원 | 전체 최대 300초, 개별 프로세스 CPU 시간 최대 90초, DB 프로세스 트리당 PID 최대 48개, RSS 합계 최대 1 GiB, DB별 임시 공간 최대 768 MiB다. 클라이언트 JVM 힙은 256 MiB, 활성 CPU는 2개, 로그는 16 MiB로 제한한다. |
| 중지와 정리 | 작업 전 fixture DB의 상태와 루프백 리스너 소유권을 확인한다. 오류 또는 한도 초과 시 중지하고 정제된 증거를 보존한다. 소유 프로세스 종료와 임시 파일 회수를 검증한다. |

운영자가 앞서 제안한 한도로 실측을 지시했다. 승인된 시험 1회를 2026-11-19에 마쳤다. 두 DB에서 각각 웜업을 포함한 208건을 실행해 반환 행을 검증했고, Observe 이벤트 104건과 오류 0건을 기록했다. 전체 실행 시간은 65.716초였다. 두 네이티브 시험 서버가 종료됐고 임시 파일 자동 정리가 통과했다. [판정 명세](../../tools/product-g5-criteria.json) · [승인 기록](../../evidence/PRODUCT-G5-PERFORMANCE-APPROVAL.json) · [실측 표본](../../evidence/PRODUCT-G5-PERFORMANCE.json)

| DB / 드라이버 | 기준 p95 (ns) | Observe p95 (ns) | 증가율 | NFR-02 |
|---|---:|---:|---:|---|
| PostgreSQL 17.11 / JDBC 42.7.14 | 676,750 | 1,000,333 | 47.8143% | FAIL |
| MySQL 8.0.46 / Connector/J 26.10.0 | 1,719,000 | 2,188,417 | 27.3076% | FAIL |

증거 검증기는 고정된 상한, 표본 수와 실행 순서를 적용한 경로별 96개 표본으로 판정을 재현했다. 이번 값은 고정 SELECT와 시험 커넥션 구성의 지연 시간이며 Observe 내부 단계의 비용을 구분하려면 추가 계측이 필요하다. 승인된 1회 실행을 소진했다. 다음 성능 시험에는 새 한도 승인과 별도 증거 기록이 필요하다. [준비 검증 증거](../../evidence/PRODUCT-G5-PERFORMANCE-PREPARATION.json)

## Observe 실행 경로 후보 (RELEASE-015)

후보는 관측 한 건에서 SHA-256 엔진을 공유하고 해시 도메인을 미리 인코딩한다. 프레임워크와 지문이 같을 때 최근 암묵 쿼리 ID를 재사용한다. 관측기는 파생 항목 한 건을 보관하며 실행을 관측할 때마다 이벤트를 전달한다. 기존 JDBC 프록시에서 자주 호출하는 메서드를 직접 위임한다. 계약 검증에서 고정 해시, 드라이버 위임, 예외 객체의 동일성과 Hibernate·MyBatis·JdbcTemplate 혼용 동작을 확인했다. Core smoke, Observe 215단언, 어댑터 196단언과 H2 10건이 통과했다. [기능 검증 증거](../../evidence/PRODUCT-G5-OBSERVE-CANDIDATE.json)

명시적으로 승인된 1회 실행에서 `--run-id OBSERVE-V2`로 같은 시험 한도와 5% 기준을 적용했다. PostgreSQL·MySQL은 각각 조회 208건과 반환 행 208개를 검증했고, Observe 이벤트 104건과 오류 0건을 기록했다. 전체 실행 시간은 64.190초였다. 두 임시 서버를 종료했고 임시 파일 정리가 통과했다. [후보 실행 승인](../../evidence/PRODUCT-G5-PERFORMANCE-OBSERVE-V2-APPROVAL.json) · [후보 실행 결과](../../evidence/PRODUCT-G5-PERFORMANCE-OBSERVE-V2-RESULT.json)

| DB / 드라이버 | 기준 p95 (ns) | Observe p95 (ns) | 변화율 | NFR-02 |
|---|---:|---:|---:|---|
| PostgreSQL 17.11 / JDBC 42.7.14 | 914,583 | 1,154,333 | +26.2141% | FAIL |
| MySQL 8.0.46 / Connector/J 26.10.0 | 2,972,625 | 2,819,708 | -5.1442% | PASS |

G5 판정은 경로별 96개 표본으로 결과를 재현한다. 기존 실패 실측과 원본 소스 버전을 함께 기록한다. 두 실행 사이에 기준 경로의 p95도 변동했다. 최적화로 인한 개선 폭을 정량화하려면 두 버전을 통제된 조건에서 비교해야 한다. 후보에 승인된 1회 시험을 소진했다. 소스에 묶인 릴리스·호환성 결과는 해당 버전의 근거로 기록한다. [기존 판정](../../evidence/PRODUCT-G5-OBSERVE-BASELINE.json) · [후보 시험 준비](../../evidence/PRODUCT-G5-OBSERVE-PREPARATION.json)

후속 시험 ID의 기능 검증은 `python3 -B tools/release-performance/verify-observe-candidate.py --run-id RUN-ID`로 실행한다. 통과하면 `evidence/PRODUCT-G5-PERFORMANCE-RUN-ID-CONTRACTS.json`에 Core·Observe·JDBC/H2 시험과 입력 해시를 한 번 기록한다. 기존 `OBSERVE-V2` 원본은 보존한다. `verify-product-g5.py --run-id RUN-ID`는 같은 시험 ID의 기능 증거와 현재 입력을 대조한다. 기능 증거가 없으면 `NOT RUN`이며, 다른 ID나 입력은 거부한다.

`python3 -B tools/run-g5-performance.py --proposal RUN-ID`는 같은 후보의 공식 1회 시험 제안을 출력한다. 메모리 압력이 정상일 때만 보호 실행을 준비하고, 명시적 1회 승인을 확보한 뒤 실측한다. 공식 +5% 판정과 자원 한도는 위와 같다.

2026-11-24 최신 `develop` 후보 `c0fb9a5`의 `OBSERVE-G5-FOLLOWUP` 기능 검증은 **PASS**다. Core 스모크, Java 17 대상 컴파일, Observe 단언 246건, JDBC 어댑터 단언 213건, 인메모리 H2 10건을 통과했다. 현재 입력 37개의 SHA-512와 프로세스·임시 파일 정리를 확인했다. 실DB 기동과 성능 시험은 각각 0건이다. 새 1회 승인과 안정된 호스트가 확보되면 같은 시험 ID로 PostgreSQL·MySQL의 공식 p95를 검증한다. [기능 증거](../../evidence/PRODUCT-G5-PERFORMANCE-OBSERVE-G5-FOLLOWUP-CONTRACTS.json)

2026-11-24 `OBSERVE-G5-FOLLOWUP`의 공식 성능 시험 1회를 승인 기록에 반영했다. 기존 한도와 기능 검증을 마친 후보의 입력 해시를 고정했다. 같은 날 사전 점검 26회에서 메모리 압력 2단계가 유지되어 공식 시험은 **NOT RUN**이다. 실행기와 DB를 기동하지 않았고 1회 승인은 사용 대기 상태다. [1회 승인 기록](../../evidence/PRODUCT-G5-PERFORMANCE-OBSERVE-G5-FOLLOWUP-APPROVAL.json)

### 현재 후보 공식 성능 인수

`OBSERVE-G5-FOLLOWUP`을 2026-11-24에 기존 승인으로 1회 실행했다. 시작 전 macOS 메모리 압력이 연속 세 번 정상 수준 1이었으며 실행 중 경고는 관측되지 않았다. 시험은 63.546초 만에 끝났다.

| DB | 기준 p95 (ns) | Observe p95 (ns) | 증가율 | 판정 |
|---|---:|---:|---:|---|
| PostgreSQL 17.11 | 732,791 | 837,291 | +14.2605% | FAIL |
| MySQL 8.0.46 | 2,037,833 | 2,344,167 | +15.0323% | FAIL |

독립 검증기로 입력 해시와 경로별 표본 96개를 대조해 p95와 판정을 재현했다. DB별 조회 208건, 결과 불일치와 오류 각각 0건, Observe 이벤트 104건을 확인했다. 두 시험 DB와 소유 프로세스 그룹을 종료하고 임시 파일 1,162개를 회수했다. 1회 승인을 사용했다. 두 DB의 p95가 +5% 상한을 넘어 Oracle 전용 환경 사전 점검은 보류한다. [실행 증거](../../evidence/PRODUCT-G5-PERFORMANCE-OBSERVE-G5-FOLLOWUP-RESULT.json)

## PostgreSQL 지연 구간 진단 (RELEASE-016)

승인한 1회 진단에서 기존 `OBSERVE-V2` fixture와 Observe 소스의 계측용 사본을 임시 작업 폴더에 빌드했다. 두 경로의 JDBC 위임에 같은 타이머를 적용했다. Observe에서는 SQL 정규화·지문·쿼리 ID 계산, 이벤트 생성·전달과 프록시 생성을 별도로 계측했다. 조회 208건과 Observe 이벤트 104건을 오류 없이 검증했다. 실측 96쌍을 보존했고, 38.683초 안에 임시 PostgreSQL 프로세스와 데이터를 회수했다. [진단 승인](../../evidence/PRODUCT-G5-POSTGRESQL-ATTRIBUTION-APPROVAL.json) · [진단 증거](../../evidence/PRODUCT-G5-POSTGRESQL-ATTRIBUTION.json)

| 배타적 구간 | 전체 96쌍 평균 차이 (µs) | Observe 최저속 5건의 평균 차이 (µs) |
|---|---:|---:|
| JDBC 위임 | -7.199 | +463.676 |
| SQL 지문·쿼리 ID | +88.639 | +187.925 |
| 이벤트 생성·전달 | +9.066 | +18.875 |
| Observe 프록시 생성 | +23.233 | +44.850 |
| 잔여 구간 | +37.558 | +279.181 |
| 총시간 | +151.299 | +994.508 |

계측 실행의 총 p95는 기준 971,959 ns, Observe 1,294,000 ns였다. 전체 비교에서 평균 차이가 가장 큰 구간은 지문·쿼리 ID 계산이었다. Observe가 가장 느렸던 5건에서는 JDBC 위임의 차이가 가장 컸다. JDBC 위임 시간에는 드라이버·네트워크·서버 시간이 함께 들어가며, 잔여 구간에는 프레임워크와 계측 비용이 포함된다. 각 Observe 표본에서 지문·이벤트 시간을 산술적으로 빼면 p95는 1,111,666 ns로 기준보다 14.3738% 높다. 이 값은 추가 분석의 우선순위를 정하는 데 사용한다. 제품 G5는 기존 `OBSERVE-V2` 실측으로 판정한다. [G5 판정](../../evidence/PRODUCT-G5-ACCEPTANCE.json)

### 정규화 바이트 후보

`OBSERVE-G5-FOLLOWUP`의 DB별 96쌍에서 Observe와 기준의 지연 차이 중앙값은 PostgreSQL 102.375 µs, MySQL 119.021 µs였다. Observe가 느린 쌍은 각각 81개와 62개였다. 이전 PostgreSQL 진단에서 지문·쿼리 ID 구간의 평균 차이는 88.639 µs였으며, 가장 느린 Observe 표본 5건의 JDBC 위임 차이는 평균 463.676 µs였다. 최신 쌍별 표본은 전체 경로 지연을 측정했다. [공식 표본](../../evidence/PRODUCT-G5-PERFORMANCE-OBSERVE-G5-FOLLOWUP-RESULT.json) · [이전 구간 진단](../../evidence/PRODUCT-G5-POSTGRESQL-ATTRIBUTION.json)

두 DB가 공유하는 `SqlShape` 경로에서 정규화 ASCII 토큰을 바이트 배열로 작성해 사용한 길이만 SHA-256에 넘긴다. 정규화 문자열 생성과 UTF-8 재인코딩을 제거했다. 버퍼는 해당 호출에서만 사용한다. 기존 지문·관측 사유·이벤트와 직전 승인·실측·계약 증거의 고정 해시를 확인했다.

`OBSERVE-SHAPE-BYTES-01`은 Core 스모크, Java 17 대상 컴파일, Observe 250단언, JDBC 어댑터 213단언, H2 10건과 오프라인 22건을 통과했다. 입력 해시 37개와 정리를 확인했다. 기능 검증 단계에서는 공식 p95를 측정하지 않았다. 새 1회 승인과 호스트 안정 확인 후 기존 +5% 기준을 적용한다. [기능 증거](../../evidence/PRODUCT-G5-PERFORMANCE-OBSERVE-SHAPE-BYTES-01-CONTRACTS.json)

2026-11-25 `OBSERVE-SHAPE-BYTES-01`의 공식 시험 1회를 승인 기록에 반영했다. 기능 증거와 공유하는 입력 11개, 고정 PostgreSQL·MySQL 바이너리와 승인 계획을 대조했다. [1회 승인 기록](../../evidence/PRODUCT-G5-PERFORMANCE-OBSERVE-SHAPE-BYTES-01-APPROVAL.json)

같은 날 시작 전 메모리 압력 1단계를 연속 세 번 확인하고, 실행 중 경고 없이 공식 시험을 63.315초에 완료했다. 승인 1회는 소진됐다.

| DB | 기준 p95 (ns) | Observe p95 (ns) | 증가율 | 판정 |
|---|---:|---:|---:|---|
| PostgreSQL 17.11 | 683,375 | 992,541 | +45.2410% | FAIL |
| MySQL 8.0.46 | 1,604,875 | 1,887,667 | +17.6208% | FAIL |

DB별 조회 208건, 결과 불일치·오류 0건, Observe 이벤트 104건을 확인했다. 경로별 표본 96개에서 p95를 재계산했고, 두 시험 DB·소유 프로세스 그룹 종료와 임시 파일 1,162개 회수를 확인했다. 두 프로파일이 +5% 상한을 초과했다. [공식 실측 증거](../../evidence/PRODUCT-G5-PERFORMANCE-OBSERVE-SHAPE-BYTES-01-RESULT.json)

### PostgreSQL 정규화·JDBC 전후 비교 계획

PostgreSQL의 직전 두 공식 시험에서 기준 p95는 732.791→683.375 µs, Observe p95는 837.291→992.541 µs였다. 쌍별 차이의 중앙값은 102.375→118.750 µs, 차이의 p95는 431.709→598.916 µs였다. 과거 구간 계측에서 느린 Observe 표본 5건의 JDBC 위임 차이는 평균 463.676 µs였고, 그중 `executeQuery`의 평균 차이는 361.250 µs였다. 그 계측의 지문 구간은 정규화·해시·쿼리 ID를 합산했다. 최신 공식 표본에는 구간 시간이 없다. [직전 공식 표본](../../evidence/PRODUCT-G5-PERFORMANCE-OBSERVE-G5-FOLLOWUP-RESULT.json) · [정규화 바이트 공식 표본](../../evidence/PRODUCT-G5-PERFORMANCE-OBSERVE-SHAPE-BYTES-01-RESULT.json) · [기존 구간 기록](../../evidence/PRODUCT-G5-POSTGRESQL-ATTRIBUTION.json)

같은 PostgreSQL 17.11 인스턴스, JDBC 42.7.14, JDK, SELECT와 8개 행 입력으로 `4eb8f40`과 `8038c2d`를 비교한다. 배치는 전→후→후→전의 네 블록이다. 각 블록은 기준·Observe를 짝으로 웜업 4쌍, 측정 16쌍 수행해 총 160회 실행한다. 각 행은 측정 구간에서 두 시작 순서에 한 번씩 배정한다. 동시 1회, 연속 1초당 최대 8회, 시작 간격 최소 125 ms, 전체 300초와 기존 자원 상한을 제안한다.

정규화 토큰 생성과 지문·쿼리 ID 계산을 배타적으로 계측한다. 두 경로에 같은 JDBC prepare·executeQuery·기타 위임 계측을 적용하고 이벤트 생성·전달, 프록시, 잔여 시간을 별도로 기록한다. 쌍별 차이의 중앙값과 시작 순서별·느린 표본의 구간을 비교한다. 반환 행·이벤트와 구간 합계, 프로세스 종료·정리를 검증한다. 계측 결과는 개선 대상을 정하는 데 사용한다.

읽기 전용 `python3 -B tools/release-performance/assess-local-observe.py postgres-comparison-plan`은 저장 표본과 이전 구간 합계를 재검산하고 미승인 계획을 출력한다. 두 소스를 같은 Java 17 대상으로 컴파일하고 공통 Observe 계약을 적용해 각각 250단언을 통과했다. Core 스모크, 오프라인 24건과 정리도 통과했다.

보호 실행기 `python3 -B tools/release-performance/run-postgres-comparison.py prepare`는 고정 소스 해시와 PostgreSQL 바이너리를 확인하고, 현재 관측 불가 사유 전달을 보존한 임시 소스를 두 변형으로 나누어 Java 17 대상으로 컴파일한다. 각 블록은 새 JVM에서 실행하며 한 물리 연결을 블록 내 두 경로가 공유한다. 네 블록은 하나의 DB와 fixture를 공유한다. 블록 사이에는 부모 실행기가 거리 하한 125 ms를 별도로 확보하고 검증한다. 메모리 압력은 시작 전과 소유 프로세스 감시 중에 확인한다.

보호 준비는 PASS다. 새 오프라인 검증 14건에서 구간 합, 순서, 이벤트 일치, 승인 차단 및 합성 프로세스 회수를 확인했다. 실행기는 `proposal` 모드가 출력한 해시에 대해 1회 승인을 확인한 뒤 같은 입력 해시로 `run`을 실행한다. `verify`는 진단 보고서의 쌍별 구간 집계, 경로 순서별 중앙값, 블록별 가장 느린 Observe 2쌍의 동일 표본 구간 차이와 정리를 재검산한다. 진단은 PostgreSQL과 MySQL의 공식 G5 판정을 변경하지 않는다.

2026-11-25 승인된 `POSTGRES-OBSERVE-ABBA-01`을 1회 시작했다. 시작 직전 호스트 메모리 압력은 1이었고 첫 블록 도중 2로 올라 실행기가 `HOST_MEMORY_PRESSURE`로 중단했다. 완료된 블록은 0/4이며, 결과는 **INCONCLUSIVE**다. 격리 PostgreSQL과 소유 프로세스 그룹을 종료하고 임시 파일 1,052개를 회수했다. 결과 검증기는 불완전 기록의 진단 PASS를 거부했다. 이 실행에서 제품 변경 대상을 정할 구간 표본은 확보하지 못했다. [1회 승인](../../evidence/PRODUCT-G5-POSTGRES-OBSERVE-ABBA-01-APPROVAL.json) · [중단 증거](../../evidence/PRODUCT-G5-POSTGRES-OBSERVE-ABBA-01-RESULT.json)

안정적인 시험 환경을 확인한 뒤, 별도 진단 ID에 대한 준비와 새 1회 승인을 거쳐 전후 비교를 다시 실행한다. 유효한 진단으로 수정 대상을 정하고 기능 검증과 새 시험 ID의 승인을 마친 뒤 PostgreSQL·MySQL 공식 인수로 이어간다. 공식 두 DB 인수는 **NOT RUN**이다.
### 안정성 확인 후 PostgreSQL 재진단

`POSTGRES-OBSERVE-ABBA-02`는 5초 간격으로 메모리 압력 1을 7회 확인하고 같은 상한으로 한 번 실행했다. 4/4 블록에서 조회·행 검증 각 160건, 관측 이벤트 80건, 측정 64쌍을 확인했다. 시작 간격 하한은 125.051584 ms, 연속 1초의 보수적 상한은 8회다. 실행 후 프로세스 그룹을 종료하고 임시 파일 1,055개를 회수했다. 독립 검증기가 구간 집계를 재현했다. [재진단 승인](../../evidence/PRODUCT-G5-POSTGRES-OBSERVE-ABBA-02-APPROVAL.json) · [검증된 표본](../../evidence/PRODUCT-G5-POSTGRES-OBSERVE-ABBA-02-RESULT.json)

블록별 Observe−기준 차이의 중앙값은 지문·ID 계산 37.0~78.1 µs, 정규화 25.0~37.7 µs였다. JDBC 실행의 중앙값은 −48.2~+48.2 µs로 방향이 바뀌었다. 각 블록에서 Observe가 가장 느린 두 쌍의 JDBC 실행 차이 평균은 +148.1~+214.0 µs였다. 지문·ID의 반복 비용을 우선 검토한다. 이 계측은 JDBC 지연을 서버·드라이버·호스트로 분리하거나 두 코드의 지연 순위를 확정하지 않는다. 후보 기능 검증을 마친 뒤 새 시험 ID로 두 DB 공식 인수를 진행한다.

### SHA-256 초기화 개선 후보

`OBSERVE-DIGEST-TEMPLATE-01`은 계산 입력을 받은 적 없는 SHA-256 원형에서 호출별 독립 인스턴스를 만든다. 복제를 지원하지 않는 제공자는 새 인스턴스를 만든다. 고정 지문·쿼리 ID와 독립 인스턴스의 결과를 대조했다. Java 17 대상 컴파일, Core 스모크, Observe 253단언, JDBC 어댑터 213단언, H2 호환성 10건과 정리가 통과했다. 기능 증거와 공식 계획의 공통 입력 해시 11개를 대조하고 같은 ID의 공식 1회 승인을 기록했다. [기능 증거](../../evidence/PRODUCT-G5-PERFORMANCE-OBSERVE-DIGEST-TEMPLATE-01-CONTRACTS.json) · [공식 1회 승인](../../evidence/PRODUCT-G5-PERFORMANCE-OBSERVE-DIGEST-TEMPLATE-01-APPROVAL.json)

2026-11-25, 호스트 메모리 압력 1을 5초 간격으로 7회 확인하고 승인된 공식 시험을 한 번 실행했다. DB별 조회·행 확인 각 208건, 오류·불일치 0건, 이벤트 104건이었다. 표본 96개씩에서 p95를 재계산했다. 시험 DB와 소유 프로세스 그룹을 종료했고 임시 파일 1,162개를 회수했다. [공식 실측 증거](../../evidence/PRODUCT-G5-PERFORMANCE-OBSERVE-DIGEST-TEMPLATE-01-RESULT.json)

| 프로파일 | 기준 p95 (µs) | Observe p95 (µs) | 변화율 | NFR-02 |
|---|---:|---:|---:|---|
| PostgreSQL | 439.250 | 592.416 | +34.8699% | FAIL |
| MySQL | 1119.959 | 1053.875 | −5.9006% | PASS |

PostgreSQL 쌍별 차이의 중앙값은 81.251 µs, p95는 270.333 µs였다. 이전 공식 시험과 호스트 기준 경로 p95가 달라 이 수치들은 이번 동일 세션의 차이를 설명한다. PostgreSQL 미통과로 제품 G5는 **BLOCKED**다. 다음 작업은 ABBA에서 확인한 남은 정규화 비용을 겨냥해 렉서 토큰 할당을 줄일 수 있는 국소 후보를 검토하고, 고정 지문·관측 불가 사유·기존 JDBC 동작을 기능 검증하는 것이다. 이후 새 시험 ID와 새 1회 승인으로 두 DB를 평가한다.

### 렉서 단어 할당 개선 후보

`OBSERVE-LEXER-WORDS-01`는 인용되지 않은 ASCII 단어의 소문자 바이트를 기존 정규화 버퍼에 직접 추가한다. 단어 경계가 정확히 일치할 때만 특수 처리를 적용하며, 부호는 직전 토큰의 정규화 바이트로 판단한다. 같은 Observe 계약을 기존·후보 렉서에 적용해 각각 291단언이 통과했다. 고정 지문·쿼리 ID, 인접 따옴표·부호, 관리 키워드와 거부 사유 우선순위를 대조했다. Core 스모크, Java 17 대상 컴파일, JDBC 어댑터 213단언, H2 호환성 10건, 정리도 통과했다. 기능 증거와 공식 계획이 공유하는 입력 해시 11개를 대조한 뒤 별도 1회 승인을 기록했다. [기능 증거](../../evidence/PRODUCT-G5-PERFORMANCE-OBSERVE-LEXER-WORDS-01-CONTRACTS.json) · [공식 1회 승인](../../evidence/PRODUCT-G5-PERFORMANCE-OBSERVE-LEXER-WORDS-01-APPROVAL.json)

2026-11-25, 메모리 압력 1이 5초 간격으로 7회 확인되어 승인된 공식 시험을 한 번 실행했다. DB별 조회·행 확인 각 208건, 오류·불일치 0건, 관측 이벤트 104건을 확인했다. 경로별 표본 96개에서 p95를 재계산했고 두 시험 DB와 소유 프로세스 그룹 종료, 임시 파일 1,162개 회수를 검증했다. [공식 실측 증거](../../evidence/PRODUCT-G5-PERFORMANCE-OBSERVE-LEXER-WORDS-01-RESULT.json)

| 프로파일 | 기준 p95 (µs) | Observe p95 (µs) | 변화율 | NFR-02 |
|---|---:|---:|---:|---|
| PostgreSQL | 419.334 | 494.500 | +17.9251% | FAIL |
| MySQL | 1722.250 | 2031.375 | +17.9489% | FAIL |

PostgreSQL의 짝별 지연 차이 중앙값은 82.000 µs로 직전 후보의 81.251 µs와 비슷했다. MySQL의 기준 경로 p95는 직전 1,119.959 µs에서 이번 1,722.250 µs로 변했다. 소스 변경의 효과를 판별하려면 같은 세션에서 두 후보를 교차 비교하고, 정규화 할당과 JDBC 실행 시간을 따로 측정해야 한다. 다음은 고정 입력으로 이 비교를 준비하는 것이다. 제품 G5는 **BLOCKED**이며 Oracle 사전 점검의 재개 조건은 두 DB 공식 인수 통과다.

### 정규화 할당과 JDBC 구간의 교차 비교

`OBSERVE-LEXER-CROSSOVER-01`은 이전 `bf2b0ab`과 현재 `4bbbc8a`의 승인 입력을 각각 23개 고정한다. PostgreSQL과 MySQL을 차례로 사용하며, DB별로 JVM 1개, 물리 JDBC 연결 1개와 같은 JdbcTemplate을 공유한다. 두 후보가 같은 행을 연속 조회하고, 네 블록 각각에서 4쌍을 웜업하고 16쌍을 측정한다. 각 블록의 8개 행마다 전→후와 후→전이 한 번씩 배정된다. DB별 총 160회, 두 DB 합계 320회이며 동시 1회, 연속 1초당 최대 8회, 시작 간격 최소 125 ms와 전체 300초 한도를 적용한다.

정규화 할당량은 렉서 생성 직전부터 지문 해시 직전까지 현재 JVM 스레드에서 할당된 바이트의 근사값을 기록한다. JDBC 실행은 각 후보의 `PreparedStatement.executeQuery()` 위임 호출만 나노초로 기록한다. 두 지표의 후보별 중앙값과 쌍별 차이를 블록별로 검증하고, 행·이벤트·지문·소유 프로세스 종료와 임시 파일 회수를 확인한다. [JDK 17 ThreadMXBean](https://docs.oracle.com/en/java/javase/17/docs/api/jdk.management/com/sun/management/ThreadMXBean.html)

`python3 -B tools/release-performance/run-lexer-crossover.py proposal`로 계획 해시를 확인한다. `prepare`는 고정 소스와 DB 바이너리 식별값을 대조하고, 두 렉서를 포함한 임시 Java 소스를 컴파일한 뒤 계측과 고정 지문을 오프라인에서 확인한다. 이후 별도 1회 승인과 5초 간격 메모리 압력 1 연속 7회가 충족되면 `run`을 실행하고 `verify`로 재검산한다. 이 비교의 용도는 공식 인수 후보 선정이다.

보호 준비는 **PASS**다. 두 렉서의 Java 17 대상 컴파일, JVM 계측과 합성 JDBC 위임, 두 렉서의 이벤트 일치, 오프라인 32건, Core 스모크, 정리가 통과했다. [준비 증거](../../evidence/PRODUCT-G5-OBSERVE-LEXER-CROSSOVER-01-PREPARATION.json)

2026-11-25 지정 계획으로 교차 실측을 1회 실행했다. DB별 160회 조회·행 검증과 160개 관측 이벤트, 측정 64쌍을 검증했다. 지문·쿼리 ID가 일치했으며 두 DB와 소유 프로세스 종료, 임시 파일 1,181개 회수가 통과했다. [교차 실측 승인](../../evidence/PRODUCT-G5-OBSERVE-LEXER-CROSSOVER-01-APPROVAL.json) · [교차 실측 증거](../../evidence/PRODUCT-G5-OBSERVE-LEXER-CROSSOVER-01-RESULT.json)

정규화 할당량 중앙값은 PostgreSQL·MySQL의 8개 블록 모두 792→288 B로 줄었다(−504 B, −63.6%). JDBC 위임 시간의 쌍별 차이 중앙값은 PostgreSQL −19.416~+24.062 µs, MySQL −1.687~+10.604 µs였고 각 DB의 4개 블록 중 3개에서 증가했다. 할당 절감의 재현성을 근거로 현재 렉서를 그대로 선택했다. JDBC 차이의 원인은 이 실측 범위에서 판별할 수 없다. 공식 호출 전체 p95는 별도 시험 ID `OBSERVE-LEXER-WORDS-02`에서 판정한다.

### 교차 비교 선정 후보의 공식 인수

`OBSERVE-LEXER-WORDS-02`는 `OBSERVE-LEXER-WORDS-01`과 동일한 공식 시험 입력 해시 23개를 사용했다. Core 스모크, Observe 291단언, JDBC 어댑터 213단언, H2 호환성 10건을 이 ID로 검증했다. 기능·공식 계획의 공통 입력 해시 11개를 재확인하고 별도 승인 1회를 기록했다. [기능 증거](../../evidence/PRODUCT-G5-PERFORMANCE-OBSERVE-LEXER-WORDS-02-CONTRACTS.json) · [공식 1회 승인](../../evidence/PRODUCT-G5-PERFORMANCE-OBSERVE-LEXER-WORDS-02-APPROVAL.json)

2026-11-25 메모리 압력 1을 5초 간격으로 7회 확인한 뒤 공식 시험을 1회 실행했다. DB별 208건의 조회·행 확인, 이벤트 104건, 오류·불일치 0건이었다. p95 재계산, 두 DB 및 프로세스 그룹 종료, 임시 파일 1,162개 회수가 통과했다. [공식 실측 증거](../../evidence/PRODUCT-G5-PERFORMANCE-OBSERVE-LEXER-WORDS-02-RESULT.json)

| 프로파일 | 기준 p95 (µs) | Observe p95 (µs) | 변화율 | NFR-02 |
|---|---:|---:|---:|---|
| PostgreSQL | 612.708 | 800.584 | +30.6632% | FAIL |
| MySQL | 1,764.417 | 1,797.375 | +1.8679% | PASS |

PostgreSQL은 같은 제품 입력의 직전 공식 시험에서 기준 p95가 419.334 µs였고 이번에는 612.708 µs였다. 이번 쌍별 차이 중앙값은 104.875 µs였다. 다음은 PostgreSQL의 같은 세션에서 기준 경로 변동을 확인하고, Observe 연결·문장 래퍼 처리와 이벤트 생성·전달, JDBC 위임 시간을 나눠 남은 비용을 좁히는 것이다. 개선 후보의 기능 검증을 거친 뒤 새 승인으로 공식 인수를 진행한다. 두 DB 모두 통과한 뒤 Oracle 전용 환경 사전 점검을 진행한다.

## 로컬 Observe 성능 진단 (RELEASE-031)

Core·Observe·JDBC·H2 기능 검증은 기존 경로로 계속한다. 공유 개발 맥의 L1은 DB 없이 JDBC 캐시 적중 경로 한 가지를 진단한다. 같은 세션에서 별도 JVM으로 WRAPPER와 HMAC 후보를 비교하고, 짝 블록마다 실행 순서를 번갈아 배정한다. 독립 블록 하나는 포크별 집계값 한 쌍을 제공한다. 포크 안의 개별 호출은 하나의 블록에 속한다.

파일럿은 동시에 포크 하나와 벤치마크 스레드 하나, 짝 블록 세 개, 포크별 1초 웜업과 측정 각 5회를 제안한다. 설정과 기준은 보정 결과를 바탕으로 정한다. 독립 블록 세 개로는 유한한 양측 95% 부호 신뢰구간을 계산하기 어렵다. 보정 뒤에 다음 비교의 회귀 허용률을 미리 고정한다. A/A 잡음 허용률은 그 절반 한 가지를 적용하며, 짝별 차이의 신뢰구간 전체가 양방향 허용 범위 안에 들어와야 한다. A/B는 두 버전 차이 자체의 상대 증가율 구간으로 평가한다. 상단이 한도 이내면 PASS, 하단이 한도를 초과하면 FAIL, 겹침·잡음·자료 부족은 INCONCLUSIVE다. 호출당 ns와 할당 바이트의 짝별 차이 중앙값 및 구간도 진단에 남긴다. 보정 중에는 회귀 한도를 미정으로 둔다.

JVM은 힙 512 MiB와 활성 프로세서 2개를 제안한다. 자원 기록은 별도로 경과 600초, 프로세스 트리 합산 RSS 1 GiB, 트리 누적 CPU 180초, 프로세스별 최대 CPU 90초, 동시 측정 포크 1개를 검증한다. 이 한도는 A/A와 가능한 A/B를 합친 한 실행 묶음에 적용한다. 향후 보호 실행기는 실행 중 소유 프로세스 트리 전체를 감시하고 정리를 확인해야 한다. JVM 옵션은 힙과 JVM이 인식하는 프로세서 수에 적용된다. 부하 평균·스왑 여유·전원 상태는 보정 자료로 기록한다. 시작 후 메모리 경고 혹은 자원 증거 누락은 INCONCLUSIVE다. 한도는 승인용 제안이며, 이 도구는 기록된 증거를 점검한다.

`python3 -B tools/release-performance/assess-local-observe.py plan`으로 L1 제안과 기존 공식 검증기에서 읽은 L2 한도를 확인한다. `l1` 모드는 표준 입력에서 `workload_started`, `regression_limit_percent`(미정 시 null), 두 수의 쌍 배열인 `aa_ns_per_op`, `ab_ns_per_op`, `ab_alloc_bytes_per_op`, 한도 항목 실측값과 `memory_warning_observed`·`cleanup_confirmed`를 담은 `resources`를 읽는다. `l2-progress` 모드는 중단된 실행기의 기록을 표준 입력에서 받아 개시한 DB의 INCONCLUSIVE와 기동 전 DB의 NOT RUN을 구분한다. 완료된 개별 DB 표본이 있다면 기록된 p95를 재현하고 짝별 차이 중앙값(ns)을 표시한다. 두 DB를 완주한 증거에는 공식 검증기를 사용한다.

L2는 기존의 DB별 208회, 동시 1회, 연속 1초당 시작 최대 8회, 전체 300초를 적용한다. 최근접 순위 p95 +5% 합격선과 과거 결과를 보존한다. L2 A/A를 새로 추가하거나 표본을 확대하려면 별도의 제한 계획이 필요하다. 현재 시험 예산에 호출을 추가하지 않는다. 로컬 진단은 공식 G5 판정에 영향을 주지 않는다.

## JDBC 캐시 적중 JMH 보호 실행기 (RELEASE-032)

벤치마크는 고정 ASCII SQL 하나로 `SqlObserver.prepareJdbc`를 호출한다. 초기화에서 준비 핸들의 재사용을 확인한다. DB·드라이버·네트워크·문장 실행 없이 관측 준비 경로를 측정한다. WRAPPER와 HMAC 고정 커밋에서 각각 Observe Core 소스 아홉 개를 사용한다. 개발 전용 Maven JAR 네 개와 POM, 해당 고지를 고정한다. [JMH 1.37 POM](https://github.com/openjdk/jmh/blob/1.37/pom.xml) · [고정 의존성](../../tools/release-performance/jmh-dependencies.json)

`python3 -B tools/release-performance/run-jmh-local-observe.py --prepare`로 연결을 검증한다. 고정 후보 두 개를 Java 17 대상으로 컴파일하고 각각 벤치마크 한 개가 발견되는지와 실제 캐시 적중을 확인한다. 준비 검증에서 측정 워크로드와 DB 서버 기동은 각각 0건이었다. [준비 증거](../../evidence/OBSERVE-L1-JMH-PREPARATION.json)

A/A 파일럿은 HMAC 표본마다 외부 JVM을 새로 띄우고 JMH 내부 포크를 끈다(`-f 0`). 소유 JVM을 한 번에 하나씩 실행하며 ns/op와 호출당 할당 B/op를 기록한다. 경과 시간, 프로세스 그룹 RSS·CPU, macOS 메모리 압력과 예상치 못한 자식 프로세스를 감시한다. 각 JVM의 CPU 상한에는 전체 묶음의 잔여 예산을 반영한다. 자식 회수 시 CPU 시간과 RSS 피크를 기록한다. RSS는 실행 중 표본과 종료 시 피크를 대조한다. 실행기는 소유 그룹에만 종료 신호를 보내고 정리가 불명확하면 작업 공간을 보존한다. [JMH 포크 지침](https://github.com/openjdk/jmh/blob/1.37/jmh-samples/src/main/java/org/openjdk/jmh/samples/JMHSample_12_Forking.java)

`--proposal RUN_ID`는 고정 A/A 계획과 입력 해시를 출력한다. `--run RUN_ID`는 `evidence/OBSERVE-L1-RUN_ID-APPROVAL.json`의 일치하는 명시적 1회 승인과 정상 메모리 압력을 요구한다. 빌드와 호스트 점검 후 승인을 사용한다. 정제된 출력은 로컬 `l1` 진단에 입력할 수 있다. 제안한 세 짝 블록은 보정용이다. 시간 기준과 버전 비교에 필요한 추가 독립 표본은 별도로 정한다.

### HMAC A/A 파일럿 (RELEASE-033)

최초 읽기 전용 사전 점검에서는 메모리 압력 경고 단계 2를 기록하고 승인된 `HMAC-AA-01`을 대기 상태로 두었다. 맥이 정상 단계 1로 돌아오자 보호 실행기가 고정 HMAC 후보를 확인하고 1회 승인을 사용했다. [승인](../../evidence/OBSERVE-L1-HMAC-AA-01-APPROVAL.json) · [최초 호스트 사전 점검](../../evidence/OBSERVE-L1-HMAC-AA-01-PREFLIGHT.json)

2026-11-20 실행은 **INCONCLUSIVE**다. 계획한 세 쌍 중 두 쌍의 지연 시간과 할당량을 기록했다. 총 여섯 표본 중 다섯 번째 표본 도중 메모리 압력 경고로 중단했다. 실행 시간은 53.851초, RSS 최고치는 407,552,000바이트, 총 CPU 사용 시간은 49.787초로 수치 한도 이내였다. 소유 자식 프로세스를 모두 회수하고 프로세스 그룹 종료를 확인했다. 임시 파일 55개(3,028,665바이트)를 회수했고 DB 기동은 0건이었다. 로컬 `l1` 진단 결과는 `INCONCLUSIVE / RESOURCE_EVIDENCE`다. A/B 비교 여부를 결정하기 전 새 승인과 안정된 정상 메모리 상태에서 파일럿을 다시 수행해야 한다. [실행 기록](../../evidence/OBSERVE-L1-HMAC-AA-01-RESULT.json)

## 커넥션 풀 동작 (RELEASE-009)

동일한 격리 DB·드라이버 조합에서 아래 시나리오를 별도의 제한된 기능 시험으로 검증한다. DB가 보고한 물리 세션 식별자를 대조하고 독립 커넥션으로 fixture 데이터에 미친 영향을 확인한다.

| 시나리오 | 인수 기준 |
|---|---|
| 반환과 상태 초기화 | 커밋 전 트랜잭션에서 fixture 행을 변경하고 빌린 커넥션을 닫는다. 롤백을 확인하고 다시 빌린 커넥션의 상태가 구성된 기본값과 일치하는지 검증한다. |
| 물리 커넥션 재사용 | 정상 커넥션을 반환하고 다시 빌릴 때 물리 세션 식별자가 동일한지 확인한다. 새 트랜잭션의 성공을 검증한다. |
| 세션 종료와 교체 | 커밋 전에 소유한 fixture 세션을 종료한다. 독립 커넥션으로 롤백을 확인하고 설정된 타임아웃 안에 풀이 종료된 세션을 교체하는지 확인한다. 교체 세션에서 새 트랜잭션을 커밋해 효과를 검증한다. 중단된 작업의 재실행이 없고 이미 커밋된 fixture 상태가 보존되는지 검증한다. |

두 네이티브 DB에서 HikariCP 6.3.3 기능 시험 4건이 통과했다. 미커밋 상태로 반환하면 쓰기가 롤백되고 연결 상태가 초기화돼 재사용됐다. 종료된 세션은 새 서버 세션으로 교체됐고 후속 커밋을 확인했다. 격리 DB를 종료하고 임시 파일을 회수했다. 취소·타임아웃·커밋 전 세션 유실 결과는 기존 실행 증거를 유지한다. [풀 실행 증거](../../evidence/PRODUCT-G5-POOL.json) · [복구 증거](../../evidence/DB-RECOVERY-VALIDATION.json)

## 서버 재기동 복구 (RELEASE-010)

동일한 네이티브 PostgreSQL·MySQL 프로파일에서 정상 재기동 시험 2건이 통과했다. 각 시험용 DB의 정상 종료를 확인한 뒤 같은 데이터 디렉터리를 소유권이 검증된 새 루프백 포트로 다시 열었다. 커밋 데이터 보존, 롤백 데이터 부재와 독립 커넥션에서의 후속 커밋 조회를 확인했다. 시험 프로세스와 임시 공간은 모두 회수했다. [재기동 실행 증거](../../evidence/PRODUCT-G5-RESTART.json)

## 비정상 종료와 커밋 응답 유실 (RELEASE-011)

PostgreSQL 17.11/JDBC 42.7.14와 MySQL 8.0.46/Connector/J 26.10.0에서 비정상 종료와 커밋 응답 유실을 각각 검증했다. 쓰기 트랜잭션을 열어 둔 채 소유한 서버를 강제 종료했다. 관련 프로세스 종료를 확인한 뒤 같은 데이터 디렉터리를 재기동해 기존 커밋 행 보존, 미커밋 행 부재와 후속 쓰기 커밋을 확인했다. 커밋 응답 시험에서는 단일 연결을 사용하는 로컬 중계가 실제 JDBC 커밋 응답을 폐기했다. 클라이언트가 응답을 기다리는 동안 독립 쿼리로 커밋 행을 확인했다. 클라이언트 연결을 끊자 JDBC 호출이 실패했고 `TransactionGuard`가 자동 재시도를 차단했다. 별도 연결에서 해당 쓰기가 한 번 커밋됐음을 대조했다. 두 네이티브 임시 DB에서 총 4건이 통과했다. [장애복구 증거](../../evidence/PRODUCT-G5-FAILURE.json)

### PostgreSQL·MySQL 현재 후보 기능 증거

2026-11-24 최신 `develop` 후보 입력에서 네이티브 PostgreSQL 17.11/JDBC 42.7.14와 MySQL 8.0.46/Connector/J 26.10.0을 순차 검증했다.

| 검증 범위 | PostgreSQL | MySQL | 근거 |
|---|---:|---:|---|
| JDBC 취소·타임아웃·커밋 전 세션 유실 | 3 PASS | 3 PASS | [취소·복구](../../evidence/DB-RECOVERY-VALIDATION.json) |
| HikariCP 상태 초기화·재사용 및 세션 교체 | 2 PASS | 2 PASS | [풀](../../evidence/PRODUCT-G5-POOL.json) |
| 정상 재기동 | 1 PASS | 1 PASS | [재기동](../../evidence/PRODUCT-G5-RESTART.json) |
| 비정상 종료 후 복구·커밋 응답 유실 | 2 PASS | 2 PASS | [장애복구](../../evidence/PRODUCT-G5-FAILURE.json) |

취소·복구 단언 112건, 오프라인 검사 14건과 Core 스모크를 통과했다. 현재 입력 해시, 고정 DB 바이너리 및 JDBC 버전, 시험 프로세스 종료와 임시 파일 정리를 확인했다. 이전 네 보고서의 원본은 기준선에 기록된 해시와 일치하는 상태로 `evidence/archive/observe-baseline/`에 보존했다. 새 공식 성능 측정은 **NOT RUN**이다.

## Oracle ARM64 풀 검증 (RELEASE-012)

네이티브 Linux ARM64 이미지에서 Oracle Free 23.26.4.0.0과 `ojdbc17` 23.26.4.0.0, HikariCP 6.3.3으로 기능 2건이 통과했다. 반환 시 롤백·연결 상태 초기화, 동일한 물리 세션 재사용과 독립 연결에서 후속 커밋 조회를 확인했다. 정지 중인 UDAK 컨테이너 하나를 재사용하고 새 스키마와 고정 크기 테이블스페이스에서 시험했다. 두 시험 자원을 제거하고 기존 컨테이너 12개가 모두 정지 상태임을 확인했다. [Oracle ARM 컨테이너](https://www.oracle.com/database/free/) · [Oracle 실행 증거](../../evidence/PRODUCT-G5-ORACLE.json)

## Oracle 취소와 복구 (RELEASE-013)

같은 Oracle·드라이버 조합에서 5건이 통과했다. 명시적 JDBC 취소와 쿼리 타임아웃 시험은 각각 잠금 대기를 확인한 뒤 중단됐고 ORA-01013을 반환했다. 미커밋 시험 쓰기를 보유한 세션을 종료하자 HikariCP는 다른 물리 세션을 내주었다. 독립 연결로 중단된 쓰기의 롤백과 새 커밋을 확인했다. 단일 연결의 루프백 중계가 실제 커밋 응답을 폐기한 동안 별도 쿼리로 커밋 행을 확인했다. JDBC 호출은 실패했고 `TransactionGuard`는 재시도를 차단했다. `SHUTDOWN IMMEDIATE` 후 동일한 시험 저장 공간으로 재기동해 기존 커밋·롤백 행과 후속 커밋을 검증했다. 임시 스키마·테이블스페이스·파일을 모두 제거했고 기존 컨테이너 12개는 모두 정지 상태로 돌아갔다. [Oracle 복구 증거](../../evidence/PRODUCT-G5-ORACLE-RECOVERY.json)

## 남은 제품 지원 검증

제품 G5는 **BLOCKED**다. 현재 `OBSERVE-LEXER-WORDS-02`의 공식 p95는 PostgreSQL +30.6632%로 미통과, MySQL +1.8679%로 통과했다. 기존 Oracle 풀·복구 증거는 현재 입력으로 갱신해야 하며, Oracle 동시성 파일럿과 인스턴스 비정상 종료 복구는 **NOT RUN**이다. 네이티브 SQL Server G5에는 격리된 Intel 또는 AMD x86-64 Linux 호스트가 필요하다. 정식 배포는 **BLOCKED**다. [현재 성능 증거](../../evidence/PRODUCT-G5-PERFORMANCE-OBSERVE-LEXER-WORDS-02-RESULT.json) · [기존 증거 판정](../../evidence/PRODUCT-G5-ACCEPTANCE.json) · [배포 게이트](../../evidence/PHASE6-GATE.json)

## 격리 네이티브 환경 준비 (RELEASE-014)

### SQL Server 보호 실행기 (RELEASE-025)

실행기는 전용 Intel 또는 AMD x86-64 Linux 호스트에서 고정된 SQL Server 2022 `linux/amd64` 이미지와 `mssql-jdbc` `13.6.2.jre11`을 사용한다. 준비 단계에서 호스트, cgroup v2, 로컬 Docker, 기존 컨테이너가 없는 상태, `overlay2`용 XFS 프로젝트 쿼터를 확인한다. 포트를 게시하지 않는 일회용 컨테이너 한 개를 생성한다. JDBC 클라이언트는 소유권이 확인된 컨테이너의 네트워크 네임스페이스에 진입해 루프백으로 연결한다. [Microsoft 플랫폼 요건](https://learn.microsoft.com/en-us/sql/linux/containers/deploy?view=sql-server-ver16) · [Docker 쓰기 계층 상한](https://docs.docker.com/reference/cli/docker/container/run/#set-storage-driver-options-per-container)

`python3 -B tools/release-provider/run-sqlserver-g5.py --prepare`로 읽기 전용 호스트 점검을 실행한다. `--proposal`은 운영자 검토를 위해 고정 입력과 시험 한도를 출력한다. `--run` 전에 운영자는 전용 네이티브 호스트, 일회용 인스턴스와 정리, SQL Server Developer EULA를 포함하는 일치하는 1회 승인 기록을 제공한다. 승인 기록 경로는 `evidence/PRODUCT-G5-SQLSERVER-APPROVAL.json`이다. 실행기는 컨테이너 생성 전에 승인을 사용 처리하고 재기동과 정리 전 소유권을 확인한다.

시험은 컨테이너 1개에 CPU 2개, RAM 4 GiB, PID 512개, 쓰기 계층 4 GiB를 적용하며 전체 실행 시간은 600초다. 동시성 검사는 트랜잭션 48건, 최대 동시 2건, 연속 1초당 시작 최대 4건으로 제한한다. 풀 초기화와 교체, JDBC 취소와 쿼리 타임아웃, 커밋 전 연결 단절, 커밋 완료 후 응답 유실을 확인한다. 비정상 종료와 정상 재기동을 한 번씩 수행해 데이터 복구를 검증한다. 실행기는 시험 결과와 정리가 확인되면 결과를 기록한다. `python3 -B tools/release-provider/verify-sqlserver-g5.py`는 오프라인으로 증거를 검증해 SQL Server 항목을 제품 G5 판정에 반영한다.

고정 의존성으로 Java 17 대상 시험 코드 컴파일이 통과했다. 오프라인 테스트 22건과 Core 스모크가 모두 통과했다. 맥에서는 컨테이너 기동 전에 `HOST_LINUX_X86_64`가 반환됐다. 네이티브 SQL Server G5는 **NOT RUN**이다. 지원 검증에는 승인된 전용 호스트와 실제 실행 증거가 필요하다. [준비 증거](../../evidence/PRODUCT-G5-SQLSERVER-PREPARATION.json) · [실행기](../../tools/release-provider/run-sqlserver-g5.py) · [증거 검증기](../../tools/release-provider/verify-sqlserver-g5.py)

지정된 시험 호스트에서 `python3 -B tools/release-provider/check-sqlserver-host.py`를 실행한다. 읽기 전용 점검은 Linux x86-64, CPU 공급사, cgroup, 로컬 Docker, 가용 자원과 로컬 고정 이미지를 확인한다. 운영자가 사용 승인과 네이티브 CPU 증빙을 제공한다. 현재 작업 환경의 결과는 `HOST_LINUX_X86_64`이며 네이티브 SQL Server G5는 **NOT RUN**이다. [호스트 점검 증거](../../evidence/PRODUCT-G5-SQLSERVER-HOST-CHECK.json) · [SQL Server 컨테이너 환경 요건](https://learn.microsoft.com/sql/linux/quickstart-install-connect-docker?view=sql-server-ver16)

### Oracle 인스턴스 시험과 로컬 게스트 준비 (RELEASE-014, RELEASE-026)

Oracle 시험 코드를 고정 드라이버로 컴파일했다. `python3 -B tools/release-provider/run-oracle-instance.py --prepare`는 로컬 고정 이미지, 아키텍처, 저장소 상한 선행조건과 정지된 관리 컨테이너 수를 확인한 뒤 시험 코드를 컴파일하고 준비 증거를 기록한다. `--run`에는 일회용 Oracle 인스턴스 1개에 대한 명시적 승인, 네이티브 ARM64 엔진과 영속 쓰기 계층의 3 GiB 상한이 필요하다. 이 구현은 XFS 프로젝트 쿼터를 적용한 Docker overlay2를 사용하며 기동 전에 Docker의 한도 수락을 확인한다. 맥의 엔진은 overlayfs를 사용해 이 저장소 선행조건을 충족하지 못했다. 기존 컨테이너 12개는 보존했다. [준비 검증 증거](../../evidence/PRODUCT-G5-ORACLE-INSTANCE-PREPARATION.json) · [Docker 저장소 한도](https://docs.docker.com/reference/cli/docker/container/run/#set-storage-driver-options-per-container)

실행 중인 Ubuntu ARM64 VM 내부의 체크아웃에서 시험 코드 컴파일 전에 `python3 -B tools/release-provider/check-oracle-guest.py`를 실행한다. 읽기 전용 점검은 cgroup v2, 가용 CPU 2개, 게스트 가용 메모리 및 Docker 용량 4 GiB, 작업 공간 여유 40 GiB를 확인한다. 기존 로컬 Docker 데몬에 컨테이너가 없는지, 볼륨 선언이 없는 정확한 고정 ARM64 이미지가 있는지도 검사한다. Docker 데이터 파일시스템은 3 GiB 이상 남아 있어야 하고 `d_type` 및 프로젝트 쿼터 강제 적용이 활성화된 XFS에 `overlay2`를 사용해야 한다. 시험 전에 전용 환경 여부를 확인한다. 승인된 시험에서는 기동 전에 Docker가 3 GiB 상한을 수락하는지 확인한다. 점검기는 로컬 메타데이터만 사용하며 `container_quota_acceptance`와 `oracle_instance_g5`를 `NOT RUN`으로 표시한다. [점검기](../../tools/release-provider/check-oracle-guest.py) · [Docker overlay2 선행조건](https://docs.docker.com/engine/storage/drivers/overlayfs-driver/#prerequisites)

2026-11-20 맥의 메모리 압력은 경고 단계 2였다. 기존 `Ubuntu 24.04 P5-001` VM은 ARM vCPU 2개, 할당 RAM 4 GiB, 가상 디스크 1개로 일시 중단 상태였다. 현재 할당 RAM에는 가용량 검사에 필요한 4 GiB 외에 게스트 OS가 사용할 여유가 없다. VM은 일시 중단 상태로 유지했고 내부 Docker 저장소는 미확인이다. 호스트 메모리 압력이 정상으로 돌아오면 게스트 세션을 보존하고 게스트 OS와 시험에 필요한 메모리를 함께 산정한다. 저장소 설정을 바꾸기 전에 Docker 데이터 전용 저장 공간을 확인한다. 게스트 점검이 통과하면 고정 fixture를 준비한다. 실제 Oracle 시험은 **NOT RUN**이다.

제안한 Oracle 시험은 활성 DB 1개, CPU 2개, RAM 3 GiB, PID 512개, 작업 시간 600초로 제한한다. 동시 트랜잭션 최대 2개에서 정확히 48건을 시작하며, 연속 1초당 시작은 최대 4건이다. 새로 만든 시험 인스턴스만 한 차례 강제 종료한다. 재기동 후 동일 DB, 새 기동 시각, 커밋 행 보존, 미커밋 쓰기 롤백과 후속 커밋을 확인한다. Oracle 신규 실행 증거는 대기 상태다.
