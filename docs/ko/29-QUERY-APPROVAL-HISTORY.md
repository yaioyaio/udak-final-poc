# 쿼리 승인·폐기 이력

[English](../en/29-QUERY-APPROVAL-HISTORY.md) | 한국어

확장 Phase 5는 승인된 SELECT를 명시적으로 변환하는 JDBC 경로에 영속적인 승인·폐기 이력을 추가한다. 실행 허용을 판정할 때 기존 승인 정책으로 Query ID, SQL과 실행 계획 fingerprint, 원본·대상, 실행 환경 버전, 유효기간과 증거를 다시 검증한다. 애플리케이션은 신뢰할 수 있는 증거를 제공한다.

## 저널 열기와 JDBC 연결

`approval-history` 모듈은 `dev.udak.rewrite.ApprovalHistory`와 `dev.udak.rewrite.jdbc.ApprovalHistoryJdbcClient`를 제공한다.

1. `ApprovalHistory.open(Path journal, Clock clock)`으로 로컬 저널을 열고 애플리케이션 종료 시 닫는다. 파일 잠금을 지원하는 로컬 POSIX 파일시스템의 신뢰할 수 있는 비공개 디렉터리에 권한 `0600`의 전용 저널을 둔다. 운영 저널은 테스트 임시 디렉터리 밖에 둔다.
2. `long approve(Rewrite.Approval approval, Rewrite.Evidence evidence)`로 승인을 등록한다. 폐기 요청에 사용할 승인 세대 번호를 반환한다. 승인·폐기 이벤트가 저널에 영속적으로 기록된 뒤 성공을 반환한다.
3. `new ApprovalHistoryJdbcClient(dataSource, environment, history, provider)`를 생성하고 `SelectiveJdbcClient.query(...)`와 같은 입력으로 `query(template, parameters, rowMapper)`를 호출한다.
4. `boolean revoke(queryId, generation)`으로 승인을 폐기한다. 이미 지난 세대에 대한 요청은 `false`를 반환한다. 교체 승인을 등록하려면 활성 세대를 먼저 폐기한다. 폐기된 세대는 저널을 다시 연 뒤에도 후속 실행을 허용할 수 없다. 이미 허용 판정을 받은 실행은 완료될 수 있다.
5. `history(queryId)`로 불변 승인·폐기 메타데이터를 조회한다. 저널에는 식별자, fingerprint, 실행 환경 버전과 증거 참조를 보존한다. 원문 SQL, 바인드 값과 자유 형식의 작업자 정보는 저널에 넣지 않는다.

## 저장과 복구

저널은 단일 로컬 소유자가 잠금으로 독점한다. 승인 세대 번호는 쿼리마다 1부터 시작하고 이벤트 순번은 저널별로 1부터 기록 순서대로 증가한다. 상한은 이벤트 4,096개이며, 활성 쿼리 승인마다 폐기 이벤트 한 건을 기록할 자리를 확보한다. 레코드가 손상됐거나 기록이 불완전하면 승인 판정용으로 저널을 열 수 없다. 이 경우 원본 파일을 보존하고 업무 재개 전에 승인 상태를 확인한다. 정상 형식의 이전 복사본에도 이후 폐기된 승인이 남아 있을 수 있으므로 복사본의 복원으로 현재 승인 상태를 입증할 수 없다. 파일 교체 방지는 신뢰할 수 있는 비공개 디렉터리에 의존하며 실행 허용은 로컬 범위에서만 제어한다.

로컬 감사 저널은 `.approval-history-local/` 아래에 두거나 `*.udak-approval-history` 형식의 파일명을 사용한다. 두 패턴은 Git 및 Docker 제외 규칙에 등록돼 있다. 운영 저널은 테스트 임시 디렉터리 밖에서 운영자가 관리하는 위치에 둔다.

## 검증

`APPROVAL-001`, `APPROVAL-002`, `APPROVAL-003`의 보호 실행기로 Core smoke와 승인 이력 및 Spring JDBC/H2 계약을 검증한다. 검증 범위는 영속화·재개방, 유효하지 않은 저널과 오래된 세대 요청의 거부, 쿼리 간 분리, 실행 허용 시점과 신규 승인이다. [요구사항과 테스트 매핑](16-TRACEABILITY.md)

```bash
python3 tools/run-approval-history.py
```

**PASS.** 신규 JDK 전용 Core 단언 65개와 고정된 H2 2.3.232의 신규 JDBC 단언 36개를 통과했다. 기존 Core smoke, 변환 정책 및 JDBC 회귀 검증, H2 동등성 8개 시나리오의 단언 323개, 격리된 Gradle의 `jar` 및 `testClasses` 작업도 통과했다. 자동 정리로 임시 파일 1,124개와 총 390,648,221바이트를 회수했다. [실행 증거](../../evidence/APPROVAL-HISTORY-VALIDATION.json)

새 전체 실DB 매트릭스는 **NOT RUN**이다. 정식 릴리스는 기존 릴리스 게이트에서 평가하며 Phase 6 G0/G5, 서명과 게시가 필요하다. 실제 JDK 17 실행, 전체 혼합 접근 데모 실행, 광범위한 DB 지원 인증에는 별도 증거가 필요하다. [릴리스 요구사항](24-STARTERS-CLI-RELEASE-GATES.md)
