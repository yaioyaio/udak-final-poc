# 기능 개발 핸드오프

[English](../en/33-FEATURE-HANDOFF.md) | 한국어

## ThingsBoard CE 외부 파일럿 소스 준비

독립 공개 애플리케이션인 ThingsBoard CE `v4.3.1.8`을 선정했다. 고정 체크아웃에서 장치 등록 성공 및 롤백 메서드를 확인했다. 기존 합성 H2 주문 재실행 결과는 별도 증거로 보존한다. [ThingsBoard 파일럿 전제조건](34-LEGACY-ADOPTION-PILOT.md#thingsboard-ce-외부-파일럿)

## 검증 범위

소스 고정, 제한 체크아웃, 대상 테스트 두 건과 UDAK Core 스모크가 통과했다. 필수 상류 의존성 POM이 로컬 캐시에 없고 상류 요청에서 응답을 받지 못했다. ThingsBoard 빌드, 격리 PostgreSQL 기준선과 Observe OFF/ON은 NOT RUN이다. [ThingsBoard 파일럿 사전 점검 증거](../../evidence/THINGSBOARD-DEVICE-PILOT-PREFLIGHT.json)

## 후속 작업

공식 의존성 해석과 호스트의 제한된 DAO 빌드·격리 PostgreSQL 실행 조건을 확인한다. 기존 메서드 두 건을 기준선으로 실행하고, 그 뒤 같은 두 메서드에 테스트 전용 Observe를 연결해 대조한다.

공개 배포는 보류한다. 공식 성능 시험과 남은 DB 지원 검증은 문서화된 선행조건을 충족한 뒤 재개한다. [배포와 지원 증거](30-RELEASE-SUPPORT-EVIDENCE.md) · [제품 G5 기준](32-PRODUCT-G5-ACCEPTANCE.md)
