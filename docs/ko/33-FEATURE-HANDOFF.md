# 기능 개발 핸드오프

[English](../en/33-FEATURE-HANDOFF.md) | 한국어

## ThingsBoard CE 외부 파일럿 의존성

독립 공개 애플리케이션인 ThingsBoard CE `v4.3.1.8`을 선정했다. 고정 체크아웃에서 장치 등록 성공 및 롤백 메서드를 확인했다. 기존 합성 H2 주문 재실행 결과는 별도 증거로 보존한다. [ThingsBoard 파일럿 전제조건](34-LEGACY-ADOPTION-PILOT.md#thingsboard-ce-외부-파일럿)

## 검증 범위

고정 체크아웃과 기존 테스트 메서드 두 건의 선정 검토를 통과했다. 공식 게시 BOM, 부모 POM, 두 라이브러리의 POM·JAR은 공급자 SHA-256 검증을 통과했다. Maven 모델 점검 직전 호스트 메모리 압력은 2단계였다. DAO 빌드, PostgreSQL 기준선과 Observe OFF/ON은 NOT RUN이다. [공식 게시본 검증](../../evidence/THINGSBOARD-TB1-OFFICIAL-ARTIFACTS.json)

## 후속 작업

로컬 DAO 빌드와 격리 PostgreSQL의 실행 자원을 확인한다. 확보한 Maven 아티팩트로 모델 검증과 테스트 컴파일을 실행한다. 기존 메서드 두 건을 모두 실행해 건너뜀 없이 통과시킨다. 그다음 테스트 Hibernate 팩토리에 Observe를 연결해 같은 두 건의 등록·롤백·관측 결과를 대조한다. 비교를 통과한 뒤 검토된 상류 SQL 변경의 탐지를 검증한다. [파일럿 절차](34-LEGACY-ADOPTION-PILOT.md#thingsboard-ce-외부-파일럿)

공개 배포는 보류한다. 공식 성능 시험과 남은 DB 지원 검증은 문서화된 선행조건을 충족한 뒤 재개한다. [배포와 지원 증거](30-RELEASE-SUPPORT-EVIDENCE.md) · [제품 G5 기준](32-PRODUCT-G5-ACCEPTANCE.md)
