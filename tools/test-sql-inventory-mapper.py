#!/usr/bin/env python3
"""Offline contract checks for the selected Mapper XML report."""

from contextlib import redirect_stderr, redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


sys.dont_write_bytecode = True
SPEC = importlib.util.spec_from_file_location("sql_inventory_mapper", Path(__file__).with_name("sql-inventory-mapper.py"))
mapper = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mapper)
BASE = "base/SQL-INVENTORY.json"
HEAD = "head/SQL-INVENTORY.json"
BASE_XML = "base/Orders.xml"
HEAD_XML = "head/Orders.xml"
ERROR = "ERROR: invalid SQL inventory input or arguments\n"


@unittest.skipUnless(os.name == "posix", "descriptor-relative inventory reads require POSIX")
class MapperReportTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.addCleanup(os.chdir, Path.cwd())
        os.chdir(directory.name)
        Path("base").mkdir()
        Path("head").mkdir()
        self.snapshot(BASE)
        self.snapshot(HEAD)

    def snapshot(self, path, **extra):
        snapshot = {"schema_version": 1, "profile": "f" * 64, "revision": "a" * 40, "dropped": 0, "entries": [], **extra}
        Path(path).write_text(json.dumps(snapshot), encoding="utf-8")

    def xml(self, path, body, *, doctype=""):
        Path(path).write_text(doctype + '<mapper namespace="SyntheticMapper">\n' + body + '\n</mapper>', encoding="utf-8")

    def invoke(self, *flags, base=(BASE_XML,), head=(HEAD_XML,)):
        return self.invoke_raw(["--base-mappers", *base, "--head-mappers", *head, *flags])

    def invoke_raw(self, args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = mapper.main(["--base", BASE, "--head", HEAD, *args])
        return code, out.getvalue(), err.getvalue()

    def report(self, code, *flags, **paths):
        actual, output, errors = self.invoke(*flags, **paths)
        self.assertEqual((actual, errors), (code, ""))
        return json.loads(output)

    def test_changes_privacy_and_report_formats(self):
        self.xml(BASE_XML, '<select id="changed">SELECT fixture_old</select>\n'
                           '<delete id="removed">DELETE FROM fixture_old</delete>\n'
                           '<select id="stable">SELECT fixture_same</select>')
        self.xml(HEAD_XML, '\n<select id="stable">SELECT fixture_same</select>\n'
                           '<select id="changed">SELECT fixture_new</select>\n'
                           '<insert id="added">INSERT INTO fixture_new VALUES (1)</insert>')
        code, output, stderr = self.invoke("--fail-on-change")
        self.assertEqual((code, stderr), (3, ""))
        report = json.loads(output)
        self.assertEqual((report["status"], report["changes_detected"], report["queries"]), ("COMPLETE", True, []))
        self.assertEqual(report["base"]["revision"], "a" * 40)
        changes = {row["classification"]: row for row in report["mapper_xml"]["changes"]}
        self.assertEqual(set(changes), {"ADDED", "CHANGED", "REMOVED"})
        self.assertIsNone(changes["ADDED"]["base"])
        self.assertIsNone(changes["REMOVED"]["head"])
        before, after = changes["CHANGED"]["base"], changes["CHANGED"]["head"]
        self.assertEqual((before["file"], before["line"], before["classification"]), (BASE_XML, 2, "SELECT"))
        self.assertEqual((after["file"], after["line"], after["classification"]), (HEAD_XML, 4, "SELECT"))
        self.assertNotEqual(before["hash"], after["hash"])
        for change in changes.values():
            for row in (change["base"], change["head"]):
                if row is not None:
                    self.assertEqual(set(row), {"file", "line", "classification", "hash"})
                    self.assertRegex(row["hash"], r"^[0-9a-f]{64}$")
        code, markdown, stderr = self.invoke("--format", "markdown")
        self.assertEqual((code, stderr), (0, ""))
        for token in ("Overall status **COMPLETE**", "## Runtime observations", "## MyBatis Mapper XML",
                      "| ADDED | head |", "| CHANGED | base |", "| REMOVED | base |", before["hash"]):
            self.assertIn(token, markdown)
        for result in (output, markdown):
            for raw in ("fixture_old", "fixture_new", "fixture_same", "SyntheticMapper"):
                self.assertNotIn(raw, result)

    def test_shared_runtime_change_is_carried_through_mapper_report(self):
        query_hash = "1" * 64
        test_hash = "2" * 64
        base_shape = {"fingerprint_hash": "3" * 64, "statement_kind": "UPDATE"}
        head_shape = {"fingerprint_hash": "4" * 64, "statement_kind": "UPDATE"}
        entries = [
            {"framework": framework, "identity": "SCOPED", "query_id_hash": query_hash,
             "declared": False, "observed": 1, "unavailable": 0, "test_ids": [test_hash]}
            for framework in ("MYBATIS", "JDBC")
        ]
        self.snapshot(BASE, entries=[{**entry, "shapes": [base_shape]} for entry in entries])
        self.snapshot(HEAD, entries=[{**entry, "shapes": [head_shape]} for entry in entries])
        declaration = '<update id="stock">UPDATE fixture SET quantity = #{quantity}</update>'
        self.xml(BASE_XML, declaration)
        self.xml(HEAD_XML, declaration)

        complete = self.report(3, "--fail-on-change")
        self.assertEqual((complete["status"], complete["changes_detected"]), ("COMPLETE", True))
        self.assertEqual(complete["mapper_xml"]["changes"], [])
        grouped, = complete["shared_shape_changes"]
        self.assertEqual((grouped["query_id_hash"], grouped["base_shape"], grouped["head_shape"]),
                         (query_hash, base_shape, head_shape))
        self.assertEqual(grouped["shared_test_ids"], [test_hash])
        self.assertEqual([row["framework"] for row in complete["queries"]], ["JDBC", "MYBATIS"])

        self.xml(HEAD_XML, declaration + '<select id="new"><include refid="fragment"/></select>')
        incomplete = self.report(2, "--fail-on-change")
        self.assertEqual((incomplete["status"], incomplete["changes_detected"]), ("INCOMPLETE", True))
        self.assertEqual(incomplete["shared_shape_changes"], complete["shared_shape_changes"])
        code, markdown, stderr = self.invoke("--format", "markdown", "--fail-on-change")
        self.assertEqual((code, stderr), (2, ""))
        self.assertEqual(markdown.count("\n### Shared SQL shape change"), 1)
        for text in ("Overall status **INCOMPLETE**", "#### JDBC_EXECUTE", "#### MYBATIS_PREPARE",
                     "## MyBatis Mapper XML", "UNSUPPORTED_INCLUDE"):
            self.assertIn(text, markdown)

    def test_database_variants_nested_attributes_and_file_order(self):
        statement = '<select id="same" %s><if test="item != null">SELECT 1</if></select>'
        self.xml(BASE_XML, statement % 'databaseId="dbOne"' + statement % 'databaseId="dbTwo"' + statement % '')
        self.xml(HEAD_XML, (statement % 'databaseId="dbOne"').replace('!=', '==')
                 + (statement % 'databaseId="dbTwo"').replace('id="same" databaseId="dbTwo"', 'databaseId="dbTwo" id="same"')
                 + statement % '')
        extra = "head/Other.xml"
        self.xml(extra, '<select id="extra">SELECT 2</select>')
        pair = self.invoke(head=(extra, HEAD_XML))
        self.assertEqual(pair, self.invoke(head=(HEAD_XML, extra)))
        changes = json.loads(pair[1])["mapper_xml"]["changes"]
        self.assertEqual(sorted(row["classification"] for row in changes), ["ADDED", "CHANGED"])

    def test_dynamic_substitution_locations_and_fragment(self):
        body = ('<select id="example" lang="XML">\nSELECT #{boundValue},\n'
                '<![CDATA[${fixtureInCdata}]]>,\n&#36;{fixtureViaXmlReference},\n'
                '<if test="item != null">\n${fixtureInNestedText}\n</if>\n</select>\n'
                '<sql id="fragment">${fixtureInFragment}</sql>\n'
                '<!-- ${fixtureInComment} -->')
        self.xml(BASE_XML, body)
        self.xml(HEAD_XML, body)
        report = self.report(0, "--fail-on-change")
        self.assertFalse(report["changes_detected"])
        section = report["mapper_xml"]
        for side in ("base_findings", "head_findings"):
            self.assertEqual([(row["line"], row["classification"]) for row in section[side]],
                             [(line, "DYNAMIC_SUBSTITUTION") for line in (4, 5, 7, 10)])
        self.assertNotIn("fixtureIn", json.dumps(report))

    def test_unsupported_content_omits_unmatched_changes(self):
        self.xml(BASE_XML, '<select id="gone">SELECT 1</select>\n<select id="changed">SELECT 1</select>')
        self.xml(HEAD_XML, '<select id="new"><include refid="fragment"/></select>\n'
                 '<insert id="newer"><selectKey>SELECT 1</selectKey>INSERT INTO fixture VALUES (1)</insert>\n'
                 '<select id="unsupported"><customTag/></select>\n'
                 '<select id="customLanguage" lang="syntheticDriver">SELECT 3</select>\n'
                 '<select id="changed">SELECT 2</select>')
        report = self.report(2, "--fail-on-change")
        section = report["mapper_xml"]
        self.assertTrue(report["changes_detected"])
        self.assertEqual((report["status"], section["status"]), ("INCOMPLETE", "INCOMPLETE"))
        self.assertEqual([row["classification"] for row in section["changes"]], ["CHANGED"])
        self.assertEqual([row["classification"] for row in section["head_findings"]],
                         ["UNSUPPORTED_INCLUDE", "UNSUPPORTED_SELECT_KEY", "UNSUPPORTED_ELEMENT", "UNSUPPORTED_LANGUAGE"])
        code, markdown, errors = self.invoke("--format", "markdown")
        self.assertEqual((code, errors), (2, ""))
        self.assertIn("Overall status **INCOMPLETE**", markdown)
        self.assertIn("Unmatched statements are omitted", markdown)
        self.assertNotIn("Unavailable observations or dropped records limit this comparison", markdown)

    def test_duplicate_and_missing_identity_are_incomplete(self):
        self.xml(BASE_XML, '<select id="duplicate">SELECT 1</select>')
        duplicate = "head/Second.xml"
        self.xml(HEAD_XML, '<select id="duplicate">SELECT 2</select><select>SELECT 3</select>')
        self.xml(duplicate, '<select id="duplicate">SELECT 4</select>')
        report = self.report(2, head=(HEAD_XML, duplicate))
        self.assertIsNone(report["changes_detected"])
        findings = report["mapper_xml"]["head_findings"]
        self.assertCountEqual([row["classification"] for row in findings],
                              ["DUPLICATE_IDENTITY", "DUPLICATE_IDENTITY", "UNSUPPORTED_IDENTITY"])

    def test_empty_side_and_existing_observation_precedence(self):
        self.xml(HEAD_XML, '<select id="new">SELECT 1</select>')
        report = self.report(3, "--fail-on-change", base=())
        self.assertEqual(report["mapper_xml"]["changes"][0]["classification"], "ADDED")
        report = self.report(3, "--fail-on-change", base=(HEAD_XML,), head=())
        self.assertEqual(report["mapper_xml"]["changes"][0]["classification"], "REMOVED")
        declared = {"framework": "JDBC", "identity": "SCOPED", "query_id_hash": "1" * 64,
                    "declared": True, "observed": 0, "unavailable": 0, "test_ids": [], "shapes": []}
        self.snapshot(HEAD, entries=[declared], dropped=1)
        report = self.report(2, "--fail-on-change", base=())
        self.assertTrue(report["changes_detected"])
        self.assertEqual(report["queries"][0]["changes"], ["STATIC_ONLY_ADDED", "DECLARATION_GAINED"])
        self.assertEqual(report["mapper_xml"]["status"], "COMPLETE")
        self.assertEqual(self.invoke(base=(), head=()), (1, "", ERROR))
        self.assertEqual(self.invoke_raw(["--head-mappers", HEAD_XML]), (1, "", ERROR))

    def test_standard_doctype_is_inert_and_nonstandard_declarations_are_rejected(self):
        with patch.object(mapper, "reject_xml", side_effect=AssertionError("entity processing called")):
            for scheme in ("https", "http"):
                doctype = ('<!DOCTYPE mapper PUBLIC "-//mybatis.org//DTD Mapper 3.0//EN" '
                           f'"{scheme}://mybatis.org/dtd/mybatis-3-mapper.dtd">\n')
                self.xml(HEAD_XML, '<select id="valid">SELECT 1</select>', doctype=doctype)
                self.report(0, base=())
        for doctype in ('<!DOCTYPE mapper SYSTEM "urn:fixture:unknown">\n', '<!DOCTYPE mapper []>\n'):
            self.xml(HEAD_XML, '<select id="valid">SELECT 1</select>', doctype=doctype)
            self.assertEqual(self.invoke(base=()), (1, "", ERROR))
        Path(HEAD_XML).write_text('<mapper namespace="fixtureMalformed"><select>', encoding="utf-8")
        self.assertEqual(self.invoke(base=()), (1, "", ERROR))

    def test_invalid_paths_never_open_snapshots_or_xml(self):
        with patch.object(mapper.inventory, "read_snapshot") as read_snapshot, patch.object(mapper.inventory, "read_bytes") as read_bytes:
            for name in ("../Orders.xml", "./Orders.xml", "/Orders.xml", "head//Orders.xml", "head/Orders.xml.bak",
                         "restricted.env.bak/Orders.xml", "head/synthetic.key.xml", "head/bad|name.xml", "head/Orders.XML"):
                with self.subTest(name=name):
                    self.assertEqual(self.invoke(base=(), head=(name,)), (1, "", ERROR))
            self.assertEqual(self.invoke(base=(), head=(HEAD_XML, HEAD_XML)), (1, "", ERROR))
            read_snapshot.assert_not_called()
            read_bytes.assert_not_called()

    def test_unsafe_files_and_resource_bounds(self):
        self.xml(BASE_XML, '<select id="one">SELECT 1</select>')
        target = Path(HEAD_XML)
        target.symlink_to(Path(BASE_XML).absolute())
        self.assertEqual(self.invoke(), (1, "", ERROR))
        target.unlink()
        os.link(BASE_XML, HEAD_XML)
        self.assertEqual(self.invoke(base=()), (1, "", ERROR))
        target.unlink()
        os.mkfifo(HEAD_XML)
        self.assertEqual(self.invoke(base=()), (1, "", ERROR))
        target.unlink()
        Path("linked").symlink_to(Path("base").absolute(), target_is_directory=True)
        self.assertEqual(self.invoke(base=(), head=("linked/Orders.xml",)), (1, "", ERROR))
        with target.open("wb") as stream:
            stream.truncate(mapper.inventory.MAX_BYTES + 1)
        self.assertEqual(self.invoke(base=()), (1, "", ERROR))
        self.xml(HEAD_XML, '<select id="one"><if test="true">SELECT 1</if></select><select id="two">SELECT 2</select>')
        for name, maximum in (("MAX_FILES", 0), ("MAX_TOTAL_BYTES", 1), ("MAX_DEPTH", 2), ("MAX_ELEMENTS", 2),
                              ("MAX_STATEMENTS", 1)):
            with self.subTest(name=name), patch.object(mapper, name, maximum):
                self.assertEqual(self.invoke(), (1, "", ERROR))


if __name__ == "__main__":
    unittest.main()
