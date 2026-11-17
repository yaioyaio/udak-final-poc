# Shared Development Guidelines for Codex / Claude Code

English | [한국어](../ko/13-AGENT-DEVELOPMENT-GUIDE.md)

## Orchestration, branches, and Git operations (confirmed 2026-11-17)

The common entry point for all contributors is [`AGENTS.md`](../../AGENTS.md). Responses and reports must be in Korean, and document filenames must use an uppercase basename with a lowercase `.md` extension.

### Orchestration and subagent delegation

- The main session is responsible for scope, prerequisites, verification, and closure. Select an available Codex model suited to the task, considering both token cost and code/document quality.
- Prefer lightweight models for simple documentation/organization, medium-tier models for ordinary implementation, and stronger models for design/security/independent review. Handle brief checks directly and avoid excessive subdivision or duplicate review.
- Perform read-only analysis in the existing workspace. Use an auxiliary worktree only when concurrent writes are necessary, with defined ownership paths and reclamation conditions. The orchestrator verifies delegated results and directly performs merges, pushes, deletion, deployment, and final verification.
- Every delegation instruction must prohibit reading secret files and outputting sensitive values, the full environment, or raw logs, and must require passing these same rules onward.

### Branches and all deliverables

1. Before editing, check `git branch --show-current` and the list of changed files. Create `feature/{today's date YYYYMMDD}-{English feature summary}` from the latest develop. Keep existing branch names and do not edit directly on main/develop.
2. For initial adoption without Git history, prepare `.gitignore` and `.dockerignore` first, then initialize on a feature branch. Do not guess a remote URL.
3. Identify local configuration/runtime files/caches/logs/build outputs/personal editing or agent histories/secrets without reading their values, and block them in both ignore files. Ignore rules alone do not exclude already tracked items; preserve the originals and remove them from the index as well.
4. Inspect all tracked/staged/unstaged/untracked/deleted files regardless of author, session, or AI tool. Preserve shared source, documentation, the Gradle Wrapper, and intentionally retained verification evidence.
5. Confirm that staged files contain no prohibited items and include all intended shared deliverables. Do not inspect by opening sensitive files or printing sensitive values in raw diffs/logs.

### Sequential merges and closure

1. After local verification, commit/push the feature branch. If GitHub Actions is enabled on the remote, disable it before the first push. Do not add or run workflows.
2. Merge the feature → develop PR, followed by the develop → main PR. Analyze and integrate conflicts to preserve both sides' functionality, and report the verification basis.
3. Refresh remote references and inspect all six local/remote feature, develop, and main references. Select one as the baseline and confirm that file diffs against each of the other five are empty. Distinguish commit ID differences caused by merge commits from file content differences.
4. Do not delete remote branches. Reclaim auxiliary worktrees immediately after the verified results are reflected in the local/remote feature branch, and recheck remaining exceptions at overall closure. Finish in the main working directory with `git switch develop`.
5. If prerequisites such as the remote URL, permissions, or branches are missing, record that step as NOT RUN. Do not represent local verification as completed remote merges or agreement among the six references.

Claim automatic cleanup only within the scope actually connected to registered runners/Git completion events. Reclaim only completed auxiliary worktrees and regenerable outputs after immediate prechecks and within resource limits; preserve originals, uncommitted/untracked material, databases, secret configuration, and recovery/audit evidence. Verify automatic execution/reclamation/preservation counts and sizes, and do not claim that arbitrary external commands are covered by cleanup.

## Bilingual documentation

- Keep the main `README.md` in English and `README-KO.md` in Korean.
- Maintain matching uppercase English filenames in `docs/en/` and `docs/ko/`, with a link to the other language in every document.
- Update both versions in the same task and keep requirement IDs, commands, versions, and test statuses aligned. Preserve every unimplemented or NOT RUN status and every limit on guarantees when translating.
- Store raw scan findings in `.security-local/` before sanitizing them for sharing. Exclude credentials, infrastructure state, dumps, captures, and sensitive scan output from Git and Docker while retaining sanitized security documents and validation evidence.
- Ignore rules exclude files from normal Git additions and Docker build contexts. They do not automatically block already tracked files or `git add -f`; inspect index filenames before Git operations. Diagnosing and fixing dependency vulnerabilities requires separate verification.

## SSOT (Single Source of Truth)

- PRD: `docs/en/01-PRD.md`
- Architecture ADR: `docs/en/00-EXECUTIVE-DECISIONS.md`, `docs/en/02-ARCHITECTURE.md`
- API contract: `docs/en/03-API-SPEC.md`
- DBMS capability: `docs/en/04-DBMS-COMPATIBILITY.md`
- Tests/Evidence: `docs/en/08-TEST-VALIDATION.md`, `evidence/`
- Implementation progress: `docs/en/09-WBS-ROADMAP.md`

## Workflow

1. Identify the requirement ID and affected API/SPI/Adapter
2. Classify risks: SQL/transaction/legacy/cross-database
3. Write existing-contract/regression tests first
4. Implement the smallest change, following SQL parameter binding/identifier allowlists
5. Run core smoke and DB tests for supported combinations
6. Record evidence that distinguishes actual PASS / BLOCKED / NOT_RUN
7. Update document traceability

## Prohibited

- Marking work as 'verified' without running tests
- Regex-based automatic conversion of all SQL
- Claiming that @Transactional guarantees multi-database atomicity
- Assuming automatic JPA flush/cache synchronization
- Concatenating SQL values or extensive security logging
- Mixing Boot3/MyBatis3 and Boot4/MyBatis4 Starter dependencies
- Marking DBMS versions with unknown support as 'supported'
- Distributing external libraries without checking their commercial-use terms

## Commands available in the current environment

```bash
./tools/run-core-smoke.sh
```

## After network access and Gradle installation

```bash
gradle :spring-boot-demo:test
# Implement Docker/Testcontainers tests separately after setting up real databases
gradle :spring-boot-demo:bootRun
```

## Example task instruction

> Extend the FR-009 approved SQL policy. Allow translation only when the source/target DBMS versions, provider version, schema version, SQL hash, and test evidence all match. First verify mismatch blocking with unit tests, then update `docs/en/16-TRACEABILITY.md` and evidence. Keep the approval policy and SQL Translator in separate modules.
