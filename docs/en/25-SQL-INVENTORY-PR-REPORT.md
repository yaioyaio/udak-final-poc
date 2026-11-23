# SQL Inventory and PR Report

English | [한국어](../ko/25-SQL-INVENTORY-PR-REPORT.md)

## Scope

Expansion Phase 1 implements `INV-001`, `INV-002` and `INV-003`. Attach the JDK-only `dev.udak.inventory.InventoryCapture` as the existing `ObservationSink` for Hibernate, MyBatis and JdbcTemplate. The adapters use their existing Observe and normalization paths. The inventory records metadata such as a SQL shape fingerprint and observation point. It collects no original SQL, bind values or connection details. Use code-owned query and test IDs free of sensitive data.

Declare known queries explicitly to create a catalog of definitions. Runtime observations show which capture points the test scenario reached. Counts describe capture-point activity, including repeated observations, and provide no evidence of execution success or commit. The supplied catalog covers declared entries only. Generic static source scanning is outside this phase.

## Capture and export

Create one capture per revision and scenario. Supply its observer to the existing Hibernate statement inspector, MyBatis interceptor and JDBC DataSource wrapper. The existing wiring examples show where to register these adapters. [Legacy Observe wiring](21-LEGACY-OBSERVE-RESULTS.md)

```java
import dev.udak.inventory.InventoryCapture;
import dev.udak.observe.Framework;
import dev.udak.observe.SqlObserver;

var capture = new InventoryCapture();
var observer = new SqlObserver(capture);
capture.declare(Framework.MYBATIS, "Order.findOpen", "Order.findOpen.contract");

try (var scope = capture.scope("Order.findOpen", "Order.findOpen.contract")) {
    // Execute the query under test on this thread.
}

String snapshot = capture.snapshotJsonWithObservedTests(revision, profile);
```

Use the same stable logical query ID on base and head so a changed fingerprint can be associated with the query. Scopes are thread-local. Establish a scope on the thread that executes the query. A fallback `OBSERVE_ID` identifies an observation and is unsuitable as a cross-fingerprint logical key. Snapshots store hashed IDs. Use `InventoryCapture.hashQueryId` or `InventoryCapture.hashTestId` to match a reference to a known scoped query or test in local code.

Export after the scenario finishes and all participating threads are quiescent. The app explicitly writes the returned JSON to `build/inventory/base/SQL-INVENTORY.json` or `build/inventory/head/SQL-INVENTORY.json`. Supply a full lowercase hexadecimal Git commit ID of 40 or 64 characters as `revision`. Use the same lowercase 64-character SHA-256 digest of the code-owned scenario and environment identifier as `profile` for both captures. Keep the exported snapshots under the ignored `build/` directory.

Use `snapshotJsonWithObservedTests(revision, profile)` to export inventory v2 with observed test links. Each `shapes[]` item includes a sorted, unique `test_ids` array alongside its fingerprint and statement kind. An accepted normalized observation adds a link only when its thread has a test scope. Declarations, unavailable fingerprints, and observations without a test scope add no link to a shape. Entry-level `test_ids` continue to include registered test references. The existing `snapshotJson` method exports v1.

The PR CLI accepts v1, v2 and mixed input pairs. It compares SQL shapes and reports observed test links per fingerprint when both v2 inputs are complete. Use the v2 inventory with the v2 dependency manifest to verify links for schema impact. [Schema impact verification](27-SCHEMA-IMPACT-REGRESSION.md#verify-observed-fingerprint-test-links)

## Generate a PR report

```bash
python3 tools/sql-inventory.py --base build/inventory/base/SQL-INVENTORY.json --head build/inventory/head/SQL-INVENTORY.json --format markdown
```

The read-only CLI prints to stdout. JSON is the default. Redirect Markdown output to a file under `build/` if needed for PR review.

| Exit | Meaning |
|---|---|
| 0 | Comparable snapshots. Changes can be present. |
| 1 | Invalid input, including incompatible profiles, or invalid usage. |
| 2 | Incomplete comparison due to unavailable or dropped observations. |
| 3 | Comparable changes detected with `--fail-on-change`. |

Use the report to review changed observed fingerprints, coverage and related test references. An entry absent from the head snapshot may reflect a coverage change. Verify the source before treating its disappearance as deletion. The capture is bounded to 128 entries and 8 test references and 8 shapes per entry. Dropped or unavailable evidence makes the comparison incomplete.

## Review observed test link changes per fingerprint

For two complete v2 snapshots, the PR report compares observed tests under the same framework, scoped Query ID and fingerprint. JSON lists the changes in `queries[].fingerprint_test_changes` with `gained_test_ids` and `lost_test_ids`. Markdown groups those hashes under each fingerprint. A lost link indicates an association absent from the head observations. When only test links change, SQL shape status stays `UNCHANGED`, and impacted test references contain only the tests gained or lost for the changed fingerprints. With `--fail-on-change`, a comparable link change exits with code 3.

`fingerprint_test_status` is `COMPARABLE` for complete v2 pairs, `MIXED_VERSIONS` when one input is v1 and the other is v2, and `INCOMPLETE` when a v2 pair has dropped or unavailable observations. Mixed and incomplete pairs omit fingerprint test deltas while continuing to report the existing query and shape comparison. Two v1 inputs produce the existing report.

```bash
python3 -B tools/run-sql-inventory.py --fingerprint-test-links
```

The protected H2 check runs the same two JDBC SQL shapes under the same Query ID in both captures. Swapping their observed tests exposes two gained and two lost associations in JSON and Markdown. Both SQL shapes remain `UNCHANGED`. The mixed and incomplete controls omit link deltas. [PR fingerprint test change evidence](../../evidence/INVENTORY-FINGERPRINT-TEST-CHANGES-VALIDATION.json)

## Map impacted test hashes to order regressions

Save the runtime JSON report produced by `tools/sql-inventory.py` as `SQL-INVENTORY-REPORT.json` and use a repository-relative path. The mapper accepts a bounded local file up to 1 MiB and reads the runtime report's schema version 1. Run it on the runtime report before the optional Mapper XML merge.

```bash
python3 -B tools/order-pr-regression.py --report build/inventory/SQL-INVENTORY-REPORT.json
```

The order pilot registers three test IDs and their fixed protected entry points. Matching uses the inventory's test ID hash.

| Registered test ID | Entry point |
|---|---|
| `case.order.place` | `ORDER_PLACEMENT_RELATED` |
| `case.order.stock-off` | `ORDER_STOCK_OFF_RELATED` |
| `case.order.stock-on` | `ORDER_STOCK_ON_RELATED` |

A complete report with registered impacts returns `READY`. A complete report with an empty impact set returns `NO_IMPACT`. Both use exit 0. `REVIEW_REQUIRED` uses exit 2 and lists `UNKNOWN_TEST_HASH`, `INCOMPLETE_REPORT`, or `MIXED_INVENTORY_VERSIONS` as applicable. The output keeps any known matches and unknown hashes. Exit 1 identifies malformed or inconsistent input. The mapper is read-only. Protected execution belongs to the order pilot harness.

```bash
python3 -B tools/run-order-schema-impact.py --pr-regression
```

The harness compares the observed H2 stock variants with a controlled empty baseline. One `READY` PR report returns distinct OFF and ON test hashes. Each selects its own protected entry point and verifies the related schema hash on fresh H2 fixtures before running the application. OFF commits and rolls back an order against inactive stock. ON verifies commit, rollback and rejection of inactive stock. Both entry points reject the unrelated control schema hash. Synthetic unregistered, mixed-version and dropped-observation controls require review. [Order stock OFF and ON replay evidence](../../evidence/ORDER-STOCK-PR-REPLAY-VALIDATION.json)

## Optional Mapper XML review (NEXT-002)

Prepare the inventory snapshots and selected local Mapper XML files for the same base and head revisions. Use the opt-in command to add a Mapper XML section to the existing inventory report.

```bash
python3 -B tools/sql-inventory-mapper.py \
  --base build/inventory/base/SQL-INVENTORY.json \
  --head build/inventory/head/SQL-INVENTORY.json \
  --base-mappers build/inventory/base/ExampleMapper.xml \
  --head-mappers build/inventory/head/ExampleMapper.xml \
  --format markdown
```

Both file-list options are required, with at least one file across the two lists. An empty list represents a revision with no selected Mapper XML. Use explicit relative paths to regular XML files. JSON includes `mapper_xml` alongside the existing observation fields. The Mapper section records additions, content changes, removals and static findings using file, line, classification and hash. It matches declarations internally by namespace, statement ID and database ID. It hashes the parsed XML declaration, including attributes and text, without its file or line. Moving a declaration to another line alone does not count as a change.

Dynamic substitution findings identify SQL text and CDATA locations for review. The scanner covers selected XML declarations and does not evaluate template expressions. Includes, nested key queries, custom scripting languages, unsupported elements and ambiguous identities can make the Mapper comparison incomplete. The report prioritizes exit `2` for incomplete coverage and uses exit `3` with `--fail-on-change` for a complete comparison with changes. Exit `1` indicates rejected input.

The parser accepts the standard MyBatis Mapper DTD declaration as a marker. It disables external resolution and uses only the selected local files. The limits include 32 Mapper files per revision, 1 MiB per XML file, 4 MiB of parsed XML across the pair and 32 levels of XML nesting. [Mapper XML reference](https://mybatis.org/mybatis-3/sqlmap-xml.html) · [Scanner source](../../tools/sql-inventory-mapper.py)

Run the offline regression with `python3 -B tools/test-sql-inventory-mapper.py`. On 2026-11-22, nine Mapper tests, twelve existing inventory CLI tests, a process-level CLI smoke check and protected Core smoke passed. The retained inventory integration evidence is tied to earlier Core input hashes. DB integration for the current revision was NOT RUN. [Verification status](16-TRACEABILITY.md#feature-first-verification)

## Local validation

```bash
python3 tools/run-sql-inventory.py
```

The bounded runner exercises the inventory and PR report and runs the existing Core smoke and real legacy H2 tests. [Traceability and validation status](16-TRACEABILITY.md)

## Actual validation and next work

The guarded run passed 13 stages, including 48 collector assertions, 14 integration assertions, 12 CLI tests, Core smoke and 10 existing H2 compatibility scenarios. The fixture compared two H2 captures from actual Hibernate, MyBatis and JdbcTemplate calls using synthetic revision IDs. The report identified one MyBatis SQL shape change, one newly observed JDBC query and two impacted test references. Validation covered malformed input and incomplete captures. The run removed 123 temporary files and 38,017,839 bytes, with no remaining scratch files. [Execution evidence and example report](../../evidence/SQL-INVENTORY-VALIDATION.json)

The JDK-only module and H2 integration were compiled with Java 17 as the target. The standalone Gradle build and a fresh four-vendor DB run are NOT RUN. The next work is expansion Phase 2, transaction boundary tracing. Link observations to Spring transaction participation and outcomes using metadata, then validate the trace through actual framework calls. [Roadmap](09-WBS-ROADMAP.md#product-expansion-phases)

## Unavailable reason counts

`InventoryCapture` records fixed reason codes when shape normalization rejects an input. It stores counts per inventory entry. JSON and Markdown reports show counts per query and for each side of the comparison. Pre-existing snapshots and one-argument sink submissions with no reason contribute to `UNSPECIFIED`. Reason counts cover accepted unavailable observations. Dropped records are tracked separately, and unavailable or dropped observations still make the report `INCOMPLETE`.

The optional `unavailable_reasons` object in schema version 1 uses the fixed codes `EMPTY_SQL`, `SQL_TOO_LONG`, `MULTIPLE_STATEMENTS`, `AMBIGUOUS_SYNTAX`, `UNSUPPORTED_SYNTAX`, `MALFORMED_SYNTAX`, `LEXER_LIMIT` and `UNSPECIFIED`. Positive counts sum to the entry's `unavailable` total. The observation event, its fingerprint and existing one-argument sink API retain their contracts. Use the two-argument sink callback to consume a reason directly.

## Review a shape change observed by MyBatis and JDBC

JSON includes `shared_shape_changes` when the observations qualify. Each group includes the scoped query hash, the base and head shapes, shared test hashes and the two observation points. Markdown shows a single review candidate with separate `MYBATIS_PREPARE` and `JDBC_EXECUTE` details. Both formats preserve framework-level evidence, and existing comparison status and exit codes still apply.

Grouping requires the same `SCOPED` query hash, one identical absent shape and one identical added shape of the same statement kind, and a test reference shared by all four entries. Both rows must have available fingerprints and both snapshots must have zero dropped records. Unchanged extra shapes may appear in either framework. Each observation point reports the supplied observation evidence. Use application assertions to establish execution counts and outcomes.

The independent H2 order regression confirmed one stock change with two observation points and zero groups in the binding-only or coverage-gap controls. [Verification evidence](../../evidence/INVENTORY-SHARED-OBSERVATION-VALIDATION.json)
