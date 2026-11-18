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

String snapshot = capture.snapshotJson(revision, profile);
```

Use the same stable logical query ID on base and head so a changed fingerprint can be associated with the query. Scopes are thread-local. Establish a scope on the thread that executes the query. A fallback `OBSERVE_ID` identifies an observation and is unsuitable as a cross-fingerprint logical key. Snapshots store hashed IDs. Use `InventoryCapture.hashQueryId` or `InventoryCapture.hashTestId` to match a reference to a known scoped query or test in local code.

Export after the scenario finishes and all participating threads are quiescent. The app explicitly writes the returned JSON to `build/inventory/base/SQL-INVENTORY.json` or `build/inventory/head/SQL-INVENTORY.json`. Supply a full lowercase hexadecimal Git commit ID of 40 or 64 characters as `revision`. Use the same lowercase 64-character SHA-256 digest of the code-owned scenario and environment identifier as `profile` for both captures. Keep the exported snapshots under the ignored `build/` directory.

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

## Local validation

```bash
python3 tools/run-sql-inventory.py
```

The bounded runner exercises the inventory and PR report and runs the existing Core smoke and real legacy H2 tests. [Traceability and validation status](16-TRACEABILITY.md)

## Actual validation and next work

The guarded run passed 13 stages, including 48 collector assertions, 14 integration assertions, 12 CLI tests, Core smoke and 10 existing H2 compatibility scenarios. The fixture compared two H2 captures from actual Hibernate, MyBatis and JdbcTemplate calls using synthetic revision IDs. The report identified one MyBatis SQL shape change, one newly observed JDBC query and two impacted test references. Validation covered malformed input and incomplete captures. The run removed 123 temporary files and 38,017,839 bytes, with no remaining scratch files. [Execution evidence and example report](../../evidence/SQL-INVENTORY-VALIDATION.json)

The JDK-only module and H2 integration were compiled with Java 17 as the target. The standalone Gradle build and a fresh four-vendor DB run are NOT RUN. The next work is expansion Phase 2, transaction boundary tracing. Link observations to Spring transaction participation and outcomes using metadata, then validate the trace through actual framework calls. [Roadmap](09-WBS-ROADMAP.md#product-expansion-phases)
