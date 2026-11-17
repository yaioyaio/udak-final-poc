# Security & Observability

English | [한국어](../ko/07-SECURITY-OBSERVABILITY.md)

## 1. SQL Injection

- Bind values with `PreparedStatement`; use a schema allowlist for identifiers.
- Do not insert user strings directly as `ORDER BY`, column names, or table names in the DSL.
- Separate original value binding from syntax analysis for Native SQL.
- The SQL fingerprint is a hash of the SQL string's exact bytes. Whitespace is included to make approvals reproducible.

## 2. Personal Data/Logging

- SQL binding values are excluded from logs, trace attributes, and metrics tags by default.
- Retain only the query hash, Query ID, DBMS, duration, and outcome.
- An arbitrary user-controlled QueryID can also enable a high-cardinality attack: require schema registration/length limits.
- Storing query text requires separate authorization, retention, and audit policies.

## 3. Proposed Operational Metrics

- `udak.query.duration`
- `udak.translation.duration`
- `udak.translation.denied`
- `udak.compatibility.unknown`
- `udak.guard.multi_datasource`
- `udak.executor.failure`

Do not duplicate existing metrics from HikariCP, Spring Actuator, OpenTelemetry, or Micrometer.

## 4. Resource Limits

- Policies for maxPageSize, maxBindCount, queryTimeout, and connectionTimeout
- Reject `UPDATE/DELETE` without WHERE by default
- Limit batchSize/statement cache size
- When separating read-only/write connections, explicitly state that the read DB may be stale

## 5. Supply Chain

- Review licenses/vulnerabilities of external SQL engines and JDBC drivers
- Pin versions, maintain an SBOM, and use dependency verification
- CI secret masking / least privileged DB credentials
- Prohibit arbitrary Provider loading; require explicit installation and signing/supply-chain policies

## 6. Repository and Build-Context Exclusions

- Use `.gitignore` and `.dockerignore` to exclude environment/authentication files, private keys and keystores, cloud/Kubernetes/SSH configuration, Terraform state/plans, database dumps/backups, and HTTP/packet captures.
- Store raw vulnerability and secret scan findings in `.security-local/`. Exclude SARIF and the designated raw scan reports as well; share only sanitized security documents and intentional validation evidence.
- Sanitized `*.example` templates may be shared, while files inside private directories remain excluded.
- Ignore rules alone do not block already tracked files or `git add -f`. Inspect index filenames separately and remove prohibited entries from the index while preserving their local originals.
- Validate exclusions with synthetic paths without opening actual sensitive files. Dependency vulnerability diagnosis and patching require separate verification.
