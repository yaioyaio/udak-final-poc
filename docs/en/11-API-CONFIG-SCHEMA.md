# Configuration / Contract Sketch (Unimplemented Design Proposal)

English | [한국어](../ko/11-API-CONFIG-SCHEMA.md)

## Candidate Starter Configuration

```yaml
udak:
  enabled: true
  sql:
    compiler-provider: jooq
    dialect-detection: strict
    max-page-size: 1000
  legacy:
    default-mode: observe
    jpa:
      enabled: true
    mybatis:
      enabled: true
    jdbc:
      enabled: true
    rewrite:
      enabled: false
      failure-policy: reject
      approval-location: classpath:udak-approvals.yml
  consistency:
    multi-datasource-local-transaction: warn
    mixed-jpa-sql: warn
    timezone-policy: utc-instant
  observability:
    enabled: true
    log-parameters: false
```

**This is an example configuration for a future UDAK Starter and does not work as configuration for the current demo.**

## Policy Tables/ERD (If a Registry Store Is Built)

```mermaid
erDiagram
    QUERY_CATALOG ||--o{ APPROVAL : has
    QUERY_CATALOG ||--o{ COMPATIBILITY_EVIDENCE : tested
    APPROVAL }o--|| COMPATIBILITY_EVIDENCE : references
    QUERY_CATALOG {
      string query_id PK
      string framework
      string source_hash
      string owner
    }
    APPROVAL {
      string approval_id PK
      string query_id FK
      string target_dialect
      string schema_version
      string provider_version
      string evidence_id FK
      string status
    }
    COMPATIBILITY_EVIDENCE {
      string evidence_id PK
      string query_id FK
      string db_version
      string result_hash
      string test_status
    }
```

## Selective Translation Runtime Policy

Input Query ID, SQL exact hash, source/target vendor, schema/provider/runtime version → look up the approval Registry → block on mismatch → run parser/translator → validate binding metadata → execute SQL.

By default, nativeSQL executes unchanged (without translation). Rewrite is prohibited without explicit approval.
