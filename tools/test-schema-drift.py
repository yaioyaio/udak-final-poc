#!/usr/bin/env python3
"""Exercise rejected schema contracts with synthetic local snapshots."""

from contextlib import redirect_stderr, redirect_stdout
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest


sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location("schema_drift", Path(__file__).with_name("schema-drift.py"))
drift = importlib.util.module_from_spec(spec)
spec.loader.exec_module(drift)
BASELINE = "baseline/SCHEMA-SNAPSHOT.json"
CURRENT = "current/SCHEMA-SNAPSHOT.json"
SCOPE = hashlib.sha256(b"udak-schema-contract-v1\nH2\ncontract_item\n").hexdigest()
COLUMN = {"table": "contract_item", "column": "id", "type": "INTEGER", "width": 0, "nullable": False}
DOCUMENT = {"schema_version": 1, "revision": "a" * 40, "scope": SCOPE, "columns": [COLUMN]}


@unittest.skipUnless(os.name == "posix", "descriptor-relative snapshot reads require POSIX")
class SchemaDriftTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.addCleanup(os.chdir, Path.cwd())
        os.chdir(directory.name)
        for path in (BASELINE, CURRENT):
            Path(path).parent.mkdir()
            Path(path).write_text(json.dumps(DOCUMENT), encoding="utf-8")

    def invoke_invalid(self, *, baseline=BASELINE, dbms="H2", tables=("contract_item",)):
        out, err = io.StringIO(), io.StringIO()
        args = ["--baseline", baseline, "--current", CURRENT, "--dbms", dbms]
        for table in tables:
            args.extend(["--table", table])
        with redirect_stdout(out), redirect_stderr(err):
            self.assertEqual(drift.main(args), 1)
        self.assertEqual(out.getvalue(), "")
        self.assertEqual(err.getvalue(), "ERROR: invalid schema drift input or scope\n")

    def test_invalid_dbms_and_selection(self):
        self.invoke_invalid(dbms="unsupported-fixture")
        self.invoke_invalid(tables=())
        self.invoke_invalid(tables=("contract_item", "contract_item"))
        self.invoke_invalid(tables=("Contract_item",))
        self.invoke_invalid(tables=("contract_item", "extra"))
        self.invoke_invalid(tables=tuple("table_" + str(i) for i in range(129)))

    def test_scope_and_actual_table_set_must_match(self):
        for replacement in (
            {"scope": "1" * 64},
            {"columns": []},
            {"columns": [{**COLUMN, "table": "extra"}]},
            {"columns": [COLUMN, {**COLUMN, "table": "extra"}]},
        ):
            with self.subTest(fields=tuple(replacement)):
                Path(CURRENT).write_text(json.dumps({**DOCUMENT, **replacement}), encoding="utf-8")
                self.invoke_invalid()

    def test_postgresql_scope_is_distinct_from_h2(self):
        pg_scope = hashlib.sha256(b"udak-schema-contract-v1\nPOSTGRESQL\ncontract_item\n").hexdigest()
        self.invoke_invalid(dbms="POSTGRESQL")
        for path in (BASELINE, CURRENT):
            Path(path).write_text(json.dumps({**DOCUMENT, "scope": pg_scope}), encoding="utf-8")
        self.invoke_invalid()
        output = io.StringIO()
        with redirect_stdout(output):
            result = drift.main(["--baseline", BASELINE, "--current", CURRENT, "--dbms", "POSTGRESQL",
                                 "--table", "contract_item"])
        self.assertEqual(result, 0)
        self.assertEqual(json.loads(output.getvalue())["status"], "MATCH")
        Path(CURRENT).write_text(json.dumps(DOCUMENT), encoding="utf-8")
        self.invoke_invalid(dbms="POSTGRESQL")

    def test_mysql_column_drift_rejects_other_dbms_scopes(self):
        mysql_scope = hashlib.sha256(b"udak-schema-contract-v1\nMYSQL\ncontract_item\n").hexdigest()
        baseline = {**DOCUMENT, "scope": mysql_scope}
        current = {**baseline, "columns": [{**COLUMN, "type": "BIGINT"}]}
        Path(BASELINE).write_text(json.dumps(baseline), encoding="utf-8")
        Path(CURRENT).write_text(json.dumps(current), encoding="utf-8")
        output = io.StringIO()
        with redirect_stdout(output):
            result = drift.main(["--baseline", BASELINE, "--current", CURRENT, "--dbms", "MYSQL",
                                 "--table", "contract_item"])
        self.assertEqual(result, 2)
        report = json.loads(output.getvalue())
        self.assertEqual((report["status"], report["dbms"]), ("DRIFT", "MYSQL"))
        self.assertEqual(report["changes"], [{
            "table": "contract_item", "column": "id", "kind": "TYPE",
            "before": {"type": "INTEGER", "width": 0, "nullable": False},
            "after": {"type": "BIGINT", "width": 0, "nullable": False},
        }])
        for other in ("H2", "POSTGRESQL"):
            self.invoke_invalid(dbms=other)
            scope = hashlib.sha256(f"udak-schema-contract-v1\n{other}\ncontract_item\n".encode("ascii")).hexdigest()
            Path(CURRENT).write_text(json.dumps({**current, "scope": scope}), encoding="utf-8")
            self.invoke_invalid(dbms="MYSQL")

    def test_rejects_invalid_metadata_and_symlinks(self):
        Path(CURRENT).write_text(json.dumps({**DOCUMENT, "columns": [{**COLUMN, "width": 16}]}), encoding="utf-8")
        self.invoke_invalid()
        Path(CURRENT).unlink()
        Path(CURRENT).symlink_to(Path(BASELINE).resolve())
        self.invoke_invalid()
        self.invoke_invalid(baseline="../outside/SCHEMA-SNAPSHOT.json")


if __name__ == "__main__":
    unittest.main()
