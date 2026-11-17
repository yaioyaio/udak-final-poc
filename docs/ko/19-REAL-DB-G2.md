# 전용 실DB G2 — 드라이버·라이선스·실행 경계

[English](../en/19-REAL-DB-G2.md) | 한국어

## 판정

**G2 미완료: PostgreSQL·MySQL·SQL Server·Oracle 모두 NOT RUN.** 승인된 전용 `RealDatabaseProvider`가 제공되지 않았다. 기존 컨테이너의 계정·접속정보를 추출하지 않았으며 DB 접속·DDL·DML·신규 컨테이너 시작은 실행하지 않았다. ARM64 호스트의 컨테이너 상태만 제한 조회했다. 실제 서버 버전·collation·운영 라이선스는 미확정이다.

드라이버 artifact·필수 의존성·라이선스 원문과 Java 17 대상 컴파일/현재 JVM 로딩은 별도 검증한다. 이것을 실DB 검증 또는 제품 배포 승인으로 대체하지 않는다. 결과는 [G2-VALIDATION.json](../../evidence/G2-VALIDATION.json), 기존 계약 회귀는 [PHASE2-VALIDATION.json](../../evidence/PHASE2-VALIDATION.json)을 따른다.

## 검증용 버전 고정

SSOT는 [g2-dependencies.json](../../tools/g2-dependencies.json)이다. Gradle 제품 의존성에 추가하거나 드라이버 JAR를 저장소에 반입하지 않는다.

| 프로파일 | 검증용 JDBC artifact | 실제 metadata 비교 버전 | 라이선스·범위 |
|---|---|---|---|
| POSTGRESQL | org.postgresql:postgresql:42.7.14 | 42.7.14 | BSD-2-Clause; shaded 구성요소 고지 포함 |
| MYSQL | com.mysql:mysql-connector-j:26.10.0 | 26.10.0 | GPLv2 + Universal FOSS Exception 1.0; 서버 8.4+ 후보 |
| SQLSERVER | com.microsoft.sqlserver:mssql-jdbc:13.6.2.jre11 | 13.6.2.0 | MIT; 서버 사용권은 별도 |
| ORACLE | com.oracle.database.jdbc:ojdbc17:23.26.4.0.0 | 23.26.4.0.0 | 실제 JAR는 FDHUT; 서버 19c+ 후보 |

필수 graph에는 `checker-qual:3.55.1`(MIT)과 `protobuf-java:4.36.1`(BSD-3-Clause)을 포함한다. 선택적 cloud/native/Kerberos/XA/OSGi 기능은 검증 범위 밖이다. PostgreSQL 내부 shaded SCRAM/stringprep 고지도 확인한다. Protobuf 라이선스는 직접 POM이 아닌 고정 부모 POM에서 상속되므로 부모 POM과 upstream LICENSE를 함께 검증한다. SQL Server JAR에는 라이선스 파일이 없어 고정 태그의 MIT 원문을 별도로 검증한다.

- [PostgreSQL 다운로드](https://jdbc.postgresql.org/download/)와 [버전별 BSD 원문](https://raw.githubusercontent.com/pgjdbc/pgjdbc/REL42.7.14/LICENSE).
- [MySQL 호환 범위](https://dev.mysql.com/doc/connector-j/en/connector-j-versions.html)와 [GPL/FOSS 원문](https://raw.githubusercontent.com/mysql/mysql-connector-j/26.10.0/LICENSE). FOSS 예외를 UDAK의 임의 독점 배포 허가로 해석하지 않는다. 8.0 서버가 필요하면 9.7.0 등 별도 고정 후보로 재검토·재검증한다.
- [Microsoft JDBC 버전](https://learn.microsoft.com/en-us/sql/connect/jdbc/download-microsoft-jdbc-driver-for-sql-server?view=sql-server-ver17)과 [MIT 원문](https://raw.githubusercontent.com/microsoft/mssql-jdbc/v13.6.2/LICENSE).
- [Oracle 다운로드·JDK/DB 범위](https://www.oracle.com/database/technologies/appdev/jdbc-downloads.html)와 [FDHUT 원문](https://download.oracle.com/otn-pub/otn_software/jdbc/FDHUT_LICENSE.txt). 해당 POM의 FUTC 표기와 실제 JAR의 `META-INF/license.txt` FDHUT 차이를 기록했다. 제품 배포 시 실제 바이너리 약관·원문 동봉·권리표시·별도 계약을 다시 확인한다.

검증용 무수정 artifact의 원문/무결성 조사를 수행했다. MySQL 배포 형태의 GPL/FOSS 예외 적용과 Oracle 조직 계약 등 제품 재배포 승인은 `NOT_GRANTED`다. DB 서버의 라이선스를 JDBC 드라이버 라이선스로 대신 승인하지 않는다. 취약점 전체 스캔 완료를 주장하지 않는다.

## 전용 연결 제공 계약

운영자가 검토한 외부 JAR에 네 `RealDatabaseProvider` 구현과 `META-INF/services/dev.udak.testkit.RealDatabaseProvider` 등록을 제공한다. 각 구현은 정확한 프로파일, programmatic `DataSource`, `dedicatedSchemaApproved() == true`를 제공해야 한다. 전용 테스트 스키마의 자신이 만든 fixture만 CREATE/DROP할 수 있어야 하며 기존 업무 테이블은 사용하지 않는다.

운영자는 비밀 파일을 에이전트에게 열게 하거나 비밀번호·접속 URL을 전달하지 않고 DataSource를 준비한다. provider는 연결/읽기 시간 제한을 적용하고, 풀/파일 로거·DriverManager logWriter·독립 JUL handler로 원문을 기록하지 않아야 한다. provider JAR 경로와 승인된 테스트 범위만 공유한다. 로컬 provider·설정 산출물은 Git/Docker 양쪽에서 제외하는 `.g2-local/`에 보관할 수 있다. 하네스는 비밀 설정을 읽거나 provider JAR를 복사·출력하지 않는다.

SQL Server 서버 컨테이너는 [공식 x86-64 Linux 지원 범위](https://learn.microsoft.com/en-us/sql/linux/containers/deploy?view=sql-server-ver17)를 따른다. ARM64의 Rosetta/QEMU 실행은 공식 시험·지원 대상이 아니다. 승인된 x86-64 원격 서버에 Java JDBC로 연결하는 경로를 준비한다. 서버의 소유·상태·리소스·사용권 확인 없이 기존 서비스를 재사용하거나 새 서버를 시작하지 않는다.

## 제한 실행

```bash
# 고정 의존성/라이선스와 드라이버 로딩만 검사; 연결 없음.
# 네 실DB 미실행이면 의도적으로 exit 2 (INCOMPLETE).
python3 tools/run-g2.py

# 운영자가 준비·검토한 전용 provider가 있을 때만 실제 4종 실행.
python3 tools/run-g2.py --run --provider-jar .g2-local/approved-providers.jar
```

한 번에 한 프로파일, 전체 360초·프로파일당 45초·자식 CPU 30초·JVM heap 256MiB/metaspace 128MiB/활성 CPU 2개로 제한한다. workspace는 2,000항목/128MiB 상한이다. 실제 드라이버 JAR/POM의 SHA512·공식 checksum·필수 graph·라이선스 entry와 원문 hash를 재확인한다. 실제 실행 클래스패스는 main 소스만 사용하고 H2 JAR와 테스트 provider 등록을 제외한다.

각 프로파일의 제품명·드라이버명·고정 metadata 버전을 확인한 뒤, CRUD/NULL/page/bind/commit/rollback/delete 10개 검사를 수행한다. 이는 최소 API capability 범위다. JOIN/batch/upsert, 시간대/collation 동등성, 전체 서버 버전 지원, Oracle 11g, 기존 ORM, 성능은 별도 검증 대상이다. DB metadata에는 실제 major/minor 숫자만 공개하고 URL/user/catalog/schema·서버 원문 문자열·원본 예외는 출력하지 않는다. Oracle metadata 형식의 실서버 확인은 아직 NOT RUN이다.

테이블 이름 `udak_p2_<12hex>`는 부모가 생성하여 실행 **전에** `.git/udak-g2/live-intents/`에 영구 기록한다. 강제 종료 때도 실행 시작·테이블 이름·정리 미확정 상태를 보존한다. CREATE 성공을 확인한 자신의 테이블만 DROP한다. CREATE/DROP/중단 결과가 불명확하면 다음 프로파일을 시작하지 않고 fixture 증거와 DB를 보존한다. 임의 재시도·자동 잔여 테이블 삭제는 하지 않는다.

stdout/stderr와 기존 JUL 로거는 provider 로딩 전부터 프로세스 종료까지 차단하고 승인된 결과 protocol만 출력한다. provider가 별도의 파일 logger/독립 handler를 설치하는 동작은 운영자 검토 경계다. 실행기 성공·실패·정상 중단은 기존 공통 guard의 단일 정리기로 연결되고, 해당 실행이 소유한 재생성 workspace만 자동 회수한다. DB·provider·비밀 설정·실행 의도/실패 증거와 기존 불명 산출물은 보존한다. 임의 외부 명령의 정리까지 보장하지 않는다.

## 이번 실행 증거

- Core smoke, 기본 SPI 74개, 외부 SPI 83개, CRUD API 313개, Spring JDBC/H2, DB 기반·실패 경로 69개 PASS. H2/proxy 계약은 실DB 결과가 아니다.
- 고정 6개 artifact의 JAR/POM checksum 12건, 원문 라이선스/부모 POM, 실제 4개 드라이버 로딩, 증거 protocol 5개 테스트 PASS. `run-g2.py`는 네 실DB NOT RUN을 반영해 exit 2 / INCOMPLETE로 종료했다.
- 최초 드라이버 검사는 클래스명에 포함된 License/Notice를 원문 파일로 오인하여 실패했다. 파일명 필터를 수정하고 Protobuf의 직접/상속 라이선스를 구분한 뒤 재검증했다. 실패 보고는 `.git/udak-g2/previous-reports/`에 보존한다.
- 최종 회귀 workspace 62개/8,493,628바이트, 최종 G2 workspace 11개/16,293,792바이트 자동 정리·잔여 없음. 드라이버 사전 조사 2회 28개/16,345,451바이트도 자동 정리했다. 기존 불명 진단 자료는 보존했다.
- 실제 실행은 javac/java와 Python 하네스다. 새로운 DB·Docker 컨테이너·Gradle·Boot/ORM 앱·성능 테스트는 시작하지 않았다. 보조 worktree 생성/회수/잔여는 0개다.

## 다음 작업

전용 연결 제공과 실제 서버 사용권·버전·안전 전제를 확정한 다음 네 실DB를 실행한다. 네 결과가 모두 PASS이고 정리·매핑 증거를 검토해야 최소 capability의 G2 완료를 판정한다. 이후 Phase 3 JPA·MyBatis·JdbcTemplate Observe/호환성 검사를 진행한다. 현재 G2 완료나 Phase 3 착수를 보고하지 않는다.
