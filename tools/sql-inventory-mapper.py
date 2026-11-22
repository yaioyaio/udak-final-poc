#!/usr/bin/env python3
"""Extend the local SQL inventory PR report with selected MyBatis Mapper XML."""

import hashlib
import json
from pathlib import Path
import runpy
import sys
from types import SimpleNamespace
from xml.parsers import expat


inventory = SimpleNamespace(**runpy.run_path(str(Path(__file__).with_name("sql-inventory.py"))))
InvalidInventory = inventory.InvalidInventory
MAX_FILES = 32  # per revision
MAX_TOTAL_BYTES = 4 * inventory.MAX_BYTES  # across both revisions
MAX_DEPTH = 32
MAX_ELEMENTS = 4096  # per file
MAX_STATEMENTS = inventory.MAX_ENTRIES  # per revision
MAX_FINDINGS = 512  # per revision
MAX_ID_LENGTH = 1024
STATEMENTS = {"select", "insert", "update", "delete"}
MAPPER_METADATA = {"cache", "cache-ref", "resultMap", "parameterMap"}
DYNAMIC_TAGS = {"bind", "choose", "foreach", "if", "otherwise", "set", "trim", "when", "where"}
XML_LANGUAGE = "org.apache.ibatis.scripting.xmltags.XMLLanguageDriver"
DTD_PUBLIC = "-//mybatis.org//DTD Mapper 3.0//EN"
DTD_SYSTEM = {scheme + "://mybatis.org/dtd/mybatis-3-mapper.dtd" for scheme in ("http", "https")}


def mapper_paths(paths):
    if len(paths) > MAX_FILES or len(set(paths)) != len(paths):
        raise InvalidInventory()
    selected = []
    for path in sorted(paths):
        parts = path.split("/")
        if len(path) > 255 or not parts[-1].endswith(".xml") or not all(
            inventory.PATH_PART.fullmatch(part) and not inventory.PRIVATE_NAME.search(part) for part in parts
        ):
            raise InvalidInventory()
        selected.append((path, parts))
    return selected


def reject_xml(*_args):
    raise InvalidInventory()


def allow_mapper_doctype(name, system, public, has_internal_subset):
    if (name != "mapper" or system not in DTD_SYSTEM or public != DTD_PUBLIC or has_internal_subset):
        reject_xml()


def xml_parser():
    parser = expat.ParserCreate(namespace_separator=" ")
    parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)
    parser.StartDoctypeDeclHandler = allow_mapper_doctype
    parser.ExternalEntityRefHandler = reject_xml
    parser.EntityDeclHandler = reject_xml
    parser.SkippedEntityHandler = reject_xml
    return parser


def location(file, line, classification, digest):
    return {"file": file, "line": line, "classification": classification, "hash": digest}


def substitution_offsets(text):
    cursor = 0
    while (start := text.find("${", cursor)) != -1:
        end = text.find("}", start + 2)
        if end == -1:
            return
        yield start
        cursor = end + 1


class MapperSide:
    def __init__(self):
        self.statements = {}
        self.findings = []
        self.duplicates = set()
        self.complete = True
        self.statement_count = 0

    def finding(self, row):
        if len(self.findings) == MAX_FINDINGS:
            raise InvalidInventory()
        self.findings.append(row)
        if row["classification"] != "DYNAMIC_SUBSTITUTION":
            self.complete = False

    def statement(self, key, row):
        self.statement_count += 1
        if self.statement_count > MAX_STATEMENTS:
            raise InvalidInventory()
        if key in self.statements:
            self.finding({**self.statements.pop(key), "classification": "DUPLICATE_IDENTITY"})
            self.duplicates.add(key)
        if key in self.duplicates:
            self.finding({**row, "classification": "DUPLICATE_IDENTITY"})
        else:
            self.statements[key] = row


class Statement:
    def __init__(self, name, attrs, line):
        self.name = name
        self.id = attrs.get("id", "")
        self.database_id = attrs.get("databaseId")
        self.line = line
        self.hash = hashlib.sha256(b"udak-mapper-xml-statement-v1\0")
        self.text_chunks = []
        self.findings = set()

    def add_token(self, *parts):
        self.hash.update(json.dumps(parts, separators=(",", ":")).encode("ascii") + b"\n")

    def flush_text(self):
        if not self.text_chunks:
            return
        text = "".join(chunk for chunk, _ in self.text_chunks)
        self.add_token("text", text)
        chunks = iter(self.text_chunks)
        chunk, source_line = next(chunks)
        start = 0
        last_offset = 0
        for position in substitution_offsets(text):
            while position >= start + len(chunk):
                start += len(chunk)
                chunk, source_line = next(chunks)
                last_offset = 0
            offset = position - start
            source_line += chunk.count("\n", last_offset, offset)
            last_offset = offset
            self.finding(source_line, "DYNAMIC_SUBSTITUTION")
        self.text_chunks.clear()

    def finding(self, line, classification):
        self.findings.add((line, classification))
        if len(self.findings) > MAX_FINDINGS:
            raise InvalidInventory()


class MapperFile:
    def __init__(self, path, raw, side):
        self.path = path
        self.file_hash = hashlib.sha256(raw).hexdigest()
        self.side = side
        self.parser = xml_parser()
        self.depth = 0
        self.elements = 0
        self.namespace = ""
        self.is_mapper = False
        self.active = None
        self.parser.StartElementHandler = self.start
        self.parser.EndElementHandler = self.end
        self.parser.CharacterDataHandler = self.text
        self.parser.CommentHandler = self.text_boundary
        self.parser.ProcessingInstructionHandler = self.text_boundary
        self.parser.StartCdataSectionHandler = self.text_boundary
        self.parser.EndCdataSectionHandler = self.text_boundary

    def text(self, value):
        if self.active is not None and value:
            self.active.text_chunks.append((value, self.parser.CurrentLineNumber))

    def text_boundary(self, *_args):
        if self.active is not None:
            self.active.flush_text()

    def start(self, name, attrs):
        self.depth += 1
        self.elements += 1
        if self.depth > MAX_DEPTH or self.elements > MAX_ELEMENTS:
            raise InvalidInventory()
        line = self.parser.CurrentLineNumber
        if self.depth == 1:
            self.is_mapper = name == "mapper"
            self.namespace = attrs.get("namespace", "")
            if not self.is_mapper or not self.namespace.strip() or len(self.namespace) > MAX_ID_LENGTH:
                self.file_finding(line, "UNSUPPORTED_MAPPER")
        elif self.depth == 2 and self.is_mapper:
            if name in STATEMENTS or name == "sql":
                self.active = Statement(name, attrs, line)
                language = attrs.get("lang")
                if name in STATEMENTS and language is not None and language.lower() != "xml" and language != XML_LANGUAGE:
                    self.active.finding(line, "UNSUPPORTED_LANGUAGE")
            elif name not in MAPPER_METADATA:
                self.file_finding(line, "UNSUPPORTED_ELEMENT")
        elif self.active is not None and name not in DYNAMIC_TAGS:
            classification = {"include": "UNSUPPORTED_INCLUDE", "selectKey": "UNSUPPORTED_SELECT_KEY"}.get(
                name, "UNSUPPORTED_ELEMENT",
            )
            self.active.finding(line, classification)
        if self.active is not None:
            self.active.flush_text()
            self.active.add_token("start", name, sorted(attrs.items()))

    def end(self, name):
        if self.active is not None:
            self.active.flush_text()
            self.active.add_token("end", name)
            if self.depth == 2:
                self.finish_statement(self.active)
                self.active = None
        self.depth -= 1

    def file_finding(self, line, classification):
        self.side.finding(location(self.path, line, classification, self.file_hash))

    def finish_statement(self, statement):
        digest = statement.hash.hexdigest()
        for line, classification in sorted(statement.findings):
            self.side.finding(location(self.path, line, classification, digest))
        if statement.name == "sql":
            return
        if (not self.namespace.strip() or len(self.namespace) > MAX_ID_LENGTH or not statement.id.strip()
                or max(len(statement.id), len(statement.database_id or "")) > MAX_ID_LENGTH):
            self.side.finding(location(self.path, statement.line, "UNSUPPORTED_IDENTITY", digest))
            return
        self.side.statement(
            (self.namespace, statement.id, statement.database_id),
            location(self.path, statement.line, statement.name.upper(), digest),
        )


def scan_side(paths, byte_budget):
    side = MapperSide()
    for path, parts in paths:
        raw = inventory.read_bytes(parts)
        byte_budget -= len(raw)
        if byte_budget < 0:
            raise InvalidInventory()
        MapperFile(path, raw, side).parser.Parse(raw, True)
    return side, byte_budget


def sort_location(row):
    return row["file"], row["line"], row["classification"], row["hash"]


def compare_mappers(base, head):
    complete = base.complete and head.complete
    changes = []
    for key in base.statements.keys() | head.statements.keys():
        before, after = base.statements.get(key), head.statements.get(key)
        if before is None or after is None:
            if not complete:
                continue
            classification = "ADDED" if before is None else "REMOVED"
        elif before["hash"] != after["hash"]:
            classification = "CHANGED"
        else:
            continue
        changes.append({"classification": classification, "base": before, "head": after})
    changes.sort(key=lambda row: (sort_location(row["head"] or row["base"]), row["classification"]))
    return {
        "status": "COMPLETE" if complete else "INCOMPLETE",
        "changes_detected": True if changes else (False if complete else None),
        "changes": changes,
        "base_findings": sorted(base.findings, key=sort_location),
        "head_findings": sorted(head.findings, key=sort_location),
    }


def format_markdown(runtime, report):
    heading, _, observations = inventory.format_markdown(runtime).partition("\n\n")
    mapper = report["mapper_xml"]
    lines = [heading, "", f"Overall status **{report['status']}**", "", "## Runtime observations", "",
             observations, "", "## MyBatis Mapper XML", "", f"Status **{mapper['status']}**"]
    if mapper["status"] == "INCOMPLETE":
        lines += ["", "Unsupported Mapper input limits this comparison. Unmatched statements are omitted."]
    lines += ["", "| Change | Side | File | Line | Classification | SHA-256 |", "| --- | --- | --- | --- | --- | --- |"]
    rows = [(change["classification"], side, change[side]) for change in mapper["changes"]
            for side in ("base", "head") if change[side] is not None]
    rows.extend(("", side, row) for side in ("base", "head") for row in mapper[side + "_findings"])
    for change, side, row in rows:
        lines.append(f"| {change} | {side} | `{row['file']}` | {row['line']} | {row['classification']} | `{row['hash']}` |")
    if not rows:
        lines += ["", "No Mapper changes or findings recorded."]
    return "\n".join(lines)


def main(argv=None):
    parser = inventory.ArgumentParser(prog="sql-inventory-mapper.py", description=__doc__, allow_abbrev=False)
    parser.add_argument("--base", required=True, metavar=inventory.FILENAME)
    parser.add_argument("--head", required=True, metavar=inventory.FILENAME)
    parser.add_argument("--base-mappers", required=True, nargs="*", metavar="XML")
    parser.add_argument("--head-mappers", required=True, nargs="*", metavar="XML")
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    parser.add_argument("--fail-on-change", action="store_true")
    try:
        args = parser.parse_args(argv)
        if not args.base_mappers and not args.head_mappers:
            raise InvalidInventory()
        base_parts, head_parts = inventory.path_parts(args.base), inventory.path_parts(args.head)
        base_paths, head_paths = mapper_paths(args.base_mappers), mapper_paths(args.head_mappers)
        runtime = inventory.compare_snapshots(inventory.read_snapshot(base_parts), inventory.read_snapshot(head_parts))
        base, budget = scan_side(base_paths, MAX_TOTAL_BYTES)
        head, _ = scan_side(head_paths, budget)
        mapper = compare_mappers(base, head)
    except (OSError, ValueError, RecursionError, NotImplementedError, LookupError, expat.ExpatError):
        print("ERROR: invalid SQL inventory input or arguments", file=sys.stderr)
        return 1
    complete = runtime["status"] == mapper["status"] == "COMPLETE"
    changed = runtime["changes_detected"] is True or mapper["changes_detected"] is True
    report = {**runtime, "status": "COMPLETE" if complete else "INCOMPLETE",
              "changes_detected": True if changed else (False if complete else None), "mapper_xml": mapper}
    print(json.dumps(report, indent=2, sort_keys=True) if args.format == "json" else format_markdown(runtime, report))
    if not complete:
        return 2
    return 3 if args.fail_on_change and changed else 0


if __name__ == "__main__":
    raise SystemExit(main())
