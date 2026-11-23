#!/usr/bin/env python3
"""Verify the SQL dependency extractor against synthetic schema metadata."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


TOOL = Path(__file__).resolve().with_name("sql-dependencies.py")
SCHEMA = Path("input/SCHEMA-SNAPSHOT.json")
ERROR = "ERROR: invalid SQL dependency input or schema\n"
COUNT = b"SELECT COUNT(order_id) FROM order_audit"
UPDATE = b"UPDATE order_stock SET available = available - ? WHERE warehouse_id = ? AND sku_id = ? AND available >= ?"
STOCK_COLUMNS = ("available", "sku_id", "warehouse_id")


@unittest.skipUnless(os.name == "posix", "descriptor-relative schema reads require POSIX")
class SqlDependenciesTest(unittest.TestCase):
    def setUp(self):
        workspace = tempfile.TemporaryDirectory()
        self.addCleanup(workspace.cleanup)
        self.directory = Path(workspace.name)
        self.schema_path = self.directory / SCHEMA
        self.schema_path.parent.mkdir()
        self.schema = {
            "schema_version": 1,
            "revision": "a" * 40,
            "scope": "b" * 64,
            "columns": [
                {"table": "order_audit", "column": column, "type": "VARCHAR", "width": 16, "nullable": False}
                for column in ("order_id", "event_code", "fixture_note")
            ],
        }
        self.schema["columns"].extend(
            {"table": "order_stock", "column": column, "type": kind, "width": 0, "nullable": False}
            for column, kind in (("warehouse_id", "INTEGER"), ("sku_id", "INTEGER"), ("available", "INTEGER"),
                                 ("reserved", "INTEGER"), ("minimum_stock", "INTEGER"), ("active", "BOOLEAN"))
        )
        self.schema_path.write_text(json.dumps(self.schema), encoding="utf-8")

    def invoke(self, sql, *arguments):
        result = subprocess.run([sys.executable, "-B", str(TOOL), *arguments], input=sql, cwd=self.directory,
                                capture_output=True, timeout=5, check=False)
        return result.returncode, result.stdout.decode("utf-8"), result.stderr.decode("utf-8")

    def assert_result(self, sql, code, reason, columns=(), *, table="order_audit"):
        status, output, error = self.invoke(sql, "--schema", str(SCHEMA))
        self.assertEqual((status, error), (code, ""))
        self.assertEqual(json.loads(output), {
            "status": "RESOLVED" if code == 0 else "UNRESOLVED",
            "reason": reason,
            "columns": [{"table": table, "column": name} for name in columns],
        })

    def test_count_resolves_the_single_referenced_column(self):
        self.assert_result(b" \tsElEcT count ( ORDER_ID )\n FrOm ORDER_AUDIT ;\n", 0, None, ("order_id",))

    def test_insert_resolves_the_referenced_columns_in_sorted_order(self):
        self.assert_result(b"INSERT INTO order_audit (order_id, Event_Code)\nVALUES (?, ?) ;", 0, None,
                           ("event_code", "order_id"))

    def test_stock_update_deduplicates_references(self):
        self.assert_result(UPDATE, 0, None, STOCK_COLUMNS, table="order_stock")

    def test_stock_update_with_flag_resolves_the_branch_specific_column(self):
        sql = b" \tuPDATE ORDER_STOCK\nSET AVAILABLE=AVAILABLE-?\nWHERE WAREHOUSE_ID=? AND SKU_ID=?"
        sql += b"\nAND AVAILABLE>=?\nAND ACTIVE=tRuE;\n"
        self.assert_result(sql, 0, None, ("active", *STOCK_COLUMNS), table="order_stock")

    def test_stock_update_resolves_distinct_assignment_target_and_source(self):
        sql = UPDATE.replace(b"available = available -", b"available = reserved -")
        sql = sql.replace(b"available >=", b"minimum_stock >=")
        self.assert_result(sql, 0, None, ("available", "minimum_stock", "reserved", "sku_id", "warehouse_id"),
                           table="order_stock")

    def test_stock_update_with_missing_reference_returns_no_columns(self):
        for sql in (UPDATE.replace(b"order_stock", b"absent"),
                    UPDATE.replace(b"SET available", b"SET absent"),
                    UPDATE.replace(b"available -", b"absent -"),
                    UPDATE.replace(b"warehouse_id =", b"absent ="),
                    UPDATE.replace(b"sku_id =", b"absent ="),
                    UPDATE.replace(b"available >=", b"absent >="),
                    UPDATE + b" AND absent = TRUE"):
            with self.subTest(sql=sql):
                self.assert_result(sql, 2, "UNKNOWN_REFERENCE")

    def test_stock_update_with_dynamic_sql_returns_no_columns(self):
        for sql in (b"<script>" + UPDATE + b"</script>",
                    UPDATE + b'<if test="activeOnly"> AND active = TRUE </if>',
                    UPDATE.replace(b"order_stock", b"${fixture_table}")):
            with self.subTest(sql=sql):
                self.assert_result(sql, 2, "DYNAMIC_SQL")

    def test_unsupported_stock_update_returns_no_columns(self):
        for sql in (UPDATE.replace(b"order_stock", b"order_stock s"),
                    UPDATE.replace(b"order_stock", b"public.order_stock"),
                    UPDATE.replace(b"order_stock", b"order_stock JOIN order_audit"),
                    UPDATE.replace(b"WHERE", b"FROM order_audit WHERE"),
                    UPDATE.replace(b"WHERE", b", reserved = reserved - ? WHERE"),
                    UPDATE.replace(b"available -", b"available +"),
                    UPDATE.replace(b"available -", b"COALESCE(available, 0) -"),
                    UPDATE.replace(b"available - ?", b"available - 1"),
                    UPDATE.replace(b"available - ?", b"available - #{amount}"),
                    UPDATE.replace(b"sku_id = ?", b"sku_id = (SELECT sku_id FROM order_stock)"),
                    UPDATE.replace(b"sku_id", b'"sku_id"'),
                    UPDATE.replace(b"sku_id", b"s.sku_id"),
                    UPDATE.replace(b" AND sku_id", b" OR sku_id"),
                    UPDATE.replace(b"sku_id = ?", b"(sku_id = ?)"),
                    UPDATE.replace(b" AND available >= ?", b""),
                    UPDATE + b" AND reserved = ?",
                    UPDATE + b" AND active = FALSE",
                    UPDATE + b" AND active = TRUE AND reserved = TRUE",
                    UPDATE + b" RETURNING available",
                    UPDATE + b" -- fixture_marker",
                    UPDATE + b"; " + COUNT):
            with self.subTest(sql=sql):
                self.assert_result(sql, 2, "UNSUPPORTED_SQL")

    def test_stock_update_rejects_special_column_names_even_in_schema(self):
        for name in ("rownum", "xmin", "where"):
            self.schema["columns"].append(
                {"table": "order_stock", "column": name, "type": "INTEGER", "width": 0, "nullable": False}
            )
        self.schema_path.write_text(json.dumps(self.schema), encoding="utf-8")
        for name in (b"rownum", b"xmin", b"where"):
            with self.subTest(name=name):
                self.assert_result(UPDATE.replace(b"available -", name + b" -"), 2, "UNSUPPORTED_SQL")

    def test_missing_tables_and_columns_are_unresolved(self):
        for sql in (b"SELECT COUNT(order_id) FROM absent", b"SELECT COUNT(absent) FROM order_audit",
                    b"INSERT INTO order_audit (order_id, absent) VALUES (?, ?)"):
            with self.subTest(sql=sql):
                self.assert_result(sql, 2, "UNKNOWN_REFERENCE")

    def test_dynamic_sql_is_unresolved(self):
        for sql in (b"<script>SELECT COUNT(order_id) FROM order_audit</script>",
                    b'SELECT COUNT(order_id) FROM order_audit <if test="fixture_marker"></if>',
                    b"SELECT COUNT(order_id) FROM ${fixture_marker}"):
            with self.subTest(sql=sql):
                self.assert_result(sql, 2, "DYNAMIC_SQL")

    def test_unsupported_sql_does_not_return_partial_references_or_source_text(self):
        for sql in (b"SELECT COUNT(order_id) FROM order_audit, other_table",
                    b"SELECT COUNT(order_id) FROM public.order_audit",
                    b"SELECT COUNT(order_id) FROM order_audit -- fixture_marker",
                    b'SELECT COUNT("order_id") FROM order_audit',
                    b"SELECT COUNT(*) FROM order_audit",
                    b"SELECT COUNT(order_id + 1) FROM order_audit",
                    b"SELECT COUNT(order_id) FROM order_audit; SELECT COUNT(order_id) FROM order_audit",
                    b"SELECT COUNT(order_id) FROM order_audit trailing",
                    b"INSERT INTO order_audit (order_id, ORDER_ID) VALUES (?, ?)",
                    b"INSERT INTO order_audit (order_id, event_code) VALUES (?)",
                    b"INSERT INTO order_audit (order_id, event_code) VALUES (?, 'fixture_marker')"):
            with self.subTest(sql=sql):
                self.assert_result(sql, 2, "UNSUPPORTED_SQL")

    def test_input_size_and_utf8_are_checked(self):
        limit = 16_384
        self.assert_result(COUNT.ljust(limit), 0, None, ("order_id",))
        for sql in (COUNT.ljust(limit + 1), COUNT + b"\xff"):
            with self.subTest(size=len(sql)):
                self.assertEqual(self.invoke(sql, "--schema", str(SCHEMA)), (1, "", ERROR))

    def test_insert_respects_the_dependency_manifest_column_limit(self):
        names = [f"fixture_{number:03d}" for number in range(129)]
        self.schema["columns"] = [{**self.schema["columns"][0], "column": name} for name in names]
        self.schema_path.write_text(json.dumps(self.schema), encoding="utf-8")
        for size in (128, 129):
            columns = ", ".join(names[:size])
            values = ", ".join(["?"] * size)
            sql = f"INSERT INTO order_audit ({columns}) VALUES ({values})".encode("ascii")
            if size == 128:
                self.assert_result(sql, 0, None, names[:size])
            else:
                self.assert_result(sql, 2, "UNSUPPORTED_SQL")

    def test_invalid_arguments_and_unsafe_schema_paths_are_rejected(self):
        link = self.directory / "linked"
        link.symlink_to(self.schema_path.parent, target_is_directory=True)
        for argv in ((), ("--schema",), ("--schema", str(self.schema_path)),
                     ("--schema", f"input/../{SCHEMA}"), ("--schema", "linked/SCHEMA-SNAPSHOT.json"),
                     ("--schema", str(SCHEMA), "--fixture-marker")):
            with self.subTest(argv=argv):
                self.assertEqual(self.invoke(COUNT, *argv), (1, "", ERROR))

    def test_invalid_schema_returns_only_the_generic_error(self):
        for schema in ({**self.schema, "schema_version": True},
                       {**self.schema, "columns": self.schema["columns"] * 2},
                       {**self.schema, "fixture_marker": "fixture_value"}):
            with self.subTest(schema=schema):
                self.schema_path.write_text(json.dumps(schema), encoding="utf-8")
                self.assertEqual(self.invoke(COUNT, "--schema", str(SCHEMA)), (1, "", ERROR))


if __name__ == "__main__":
    unittest.main()
