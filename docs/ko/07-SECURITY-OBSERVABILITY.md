# Security & Observability

[English](../en/07-SECURITY-OBSERVABILITY.md) | 한국어

## 1. SQL Injection

- 값은 `PreparedStatement` 바인딩, 식별자는 schema allowlist.
- DSL에서 `ORDER BY`, 컬럼명, 테이블명으로 사용자 문자열 직접 삽입 금지.
- Native SQL의 원본 값 바인딩과 문법 분석은 분리.
- SQL fingerprint는 SQL 문자열 exact bytes hash. 승인 재현성을 위해 whitespace까지 반영.

## 2. 개인정보/로그

- SQL 바인딩 값은 로그·trace attribute·metrics tag에 기본 미포함.
- 쿼리 해시, Query ID, DBMS, duration, outcome만 보관.
- QueryID도 사용자가 제어한 임의 값이면 high-cardinality 공격 가능: 스키마 등록/길이 제한.
- 쿼리 텍스트 저장은 별도 권한·보관기간·감사 정책 필요.

## 3. 운영 지표 제안

- `udak.query.duration`
- `udak.translation.duration`
- `udak.translation.denied`
- `udak.compatibility.unknown`
- `udak.guard.multi_datasource`
- `udak.executor.failure`

HikariCP, Spring Actuator, OpenTelemetry, Micrometer의 기존 지표는 중복 수집하지 않는다.

## 4. 리소스 제한

- maxPageSize, maxBindCount, queryTimeout, connectionTimeout 정책
- `UPDATE/DELETE` WHERE 없음 기본 거부
- batchSize/statement cache 크기 제한
- 읽기 전용/쓰기 연결 구분 시 읽기 DB stale 가능성 명시

## 5. 공급망

- 외부 SQL 엔진 및 JDBC 드라이버 라이선스/취약점 검토
- 버전 고정·SBOM·dependency verification
- CI secret masking / least privileged DB credentials
- 임의 Provider 로딩 금지, 명시적 설치 및 서명/공급망 정책

## 6. 저장소·빌드 컨텍스트 반입 차단

- `.gitignore`와 `.dockerignore`로 환경/인증 파일, 개인키·keystore, 클라우드·Kubernetes·SSH 설정, Terraform 상태/plan, DB 덤프·백업, HTTP/패킷 캡처를 제외한다.
- 원본 취약점·시크릿 검사 결과는 `.security-local/`에 보관한다. SARIF와 지정된 원본 스캔 리포트도 제외하며, 민감값을 제거한 보안 문서와 의도적인 검증 증거만 공유한다.
- 정제된 `*.example` 템플릿은 공유할 수 있지만 비밀 전용 디렉터리의 파일은 제외를 유지한다.
- 이미 추적된 파일과 `git add -f`는 ignore만으로 차단되지 않는다. 스테이지 파일 목록을 별도로 점검하고 금지 항목이 있으면 원본을 보존하면서 인덱스에서 제외한다.
- 제외 규칙 검증은 실제 민감 파일을 열지 않고 합성 경로로 수행한다. 의존성 취약점 진단·패치와는 별도 검증이다.

## Phase 3 Observe 보안 경계

기본 이벤트에는 원 SQL, bind/literal 값, 접속/계정정보, 원본 예외가 없다. 제한된 형태 fingerprint와 query ID 해시만 제공하며 승인용 정확 SQL 해시와 분리한다. 모호한 SQL은 raw hash로 폴백하지 않고 UNAVAILABLE로 기록한다. 프레임워크 자체 SQL/바인딩 로깅·외부 listener 저장소의 보안은 별도 설정/소유 범위다. 동기식 listener는 비차단·thread-safe하게 구현하고, cursor/nested ID 및 unwrap/역참조 등 관측 제외 경로를 수집 성공으로 오인하지 않는다. [검증 범위](21-LEGACY-OBSERVE-RESULTS.md).
