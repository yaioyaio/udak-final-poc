#!/usr/bin/env python3
"""Extract column references from a limited set of static SQL statements."""

import importlib.util
import json
from pathlib import Path
import re
import sys


sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location("schema_impact", Path(__file__).with_name("schema-impact.py"))
schema = importlib.util.module_from_spec(spec)
spec.loader.exec_module(schema)

MAX_SQL_BYTES = 16 * 1024
FLAGS = re.ASCII | re.IGNORECASE
IDENTIFIER = schema.NAME.pattern
END = r"\s*(?:;\s*)?"
COUNT = re.compile(
    rf"\s*select\s+count\s*\(\s*(?P<column>{IDENTIFIER})\s*\)\s*from\s+(?P<table>{IDENTIFIER}){END}",
    FLAGS,
)
INSERT = re.compile(
    rf"\s*insert\s+into\s+(?P<table>{IDENTIFIER})\s*\(\s*"
    rf"(?P<columns>{IDENTIFIER}(?:\s*,\s*{IDENTIFIER})*)\s*\)\s*"
    rf"values\s*\(\s*(?P<binds>\?(?:\s*,\s*\?)*)\s*\){END}",
    FLAGS,
)
DYNAMIC = re.compile(
    r"\$\{|</?(?:script|if|choose|when|otherwise|foreach|trim|where|set|bind|include|sql|property)(?=[\s/>])",
    FLAGS,
)
# These unquoted tokens can denote values or engine-provided columns, even if a
# supplied catalog contains a similarly named identifier.
NON_COLUMN_TOKENS = frozenset({
    "all", "current_catalog", "current_date", "current_path", "current_role", "current_schema", "current_time",
    "current_timestamp", "current_user", "default", "distinct", "false", "from", "insert", "into", "level",
    "localtime", "localtimestamp", "null", "ora_rowscn", "rowid", "rownum", "select", "session_user", "sysdate",
    "systime", "systimestamp", "system_user", "true", "unknown", "user", "values",
})


def unresolved(reason):
    return {"status": "UNRESOLVED", "reason": reason, "columns": []}


def extract_dependencies(sql: str, known_columns):
    """Return a complete column match or an SQL-free reason for a scoped catalog."""
    try:
        if len(sql) > MAX_SQL_BYTES or len(sql.encode("utf-8")) > MAX_SQL_BYTES:
            return unresolved("INPUT_LIMIT")
    except UnicodeEncodeError:
        return unresolved("UNSUPPORTED_SQL")
    if DYNAMIC.search(sql):
        return unresolved("DYNAMIC_SQL")

    if match := COUNT.fullmatch(sql):
        columns = [match["column"].lower()]
    elif match := INSERT.fullmatch(sql):
        columns = [column.strip().lower() for column in match["columns"].split(",")]
        if (len(columns) > schema.MAX_QUERY_COLUMNS or len(columns) != match["binds"].count("?")
                or len(columns) != len(set(columns))):
            return unresolved("UNSUPPORTED_SQL")
    else:
        return unresolved("UNSUPPORTED_SQL")

    table = match["table"].lower()
    if NON_COLUMN_TOKENS.intersection((table, *columns)):
        return unresolved("UNSUPPORTED_SQL")
    references = {(table, column) for column in columns}
    if not references.issubset(known_columns):
        return unresolved("UNKNOWN_REFERENCE")
    return {"status": "RESOLVED", "reason": None,
            "columns": [{"table": table, "column": column} for table, column in sorted(references)]}


def main(argv=None):
    parser = schema.inventory.ArgumentParser(prog="sql-dependencies.py", description=__doc__, allow_abbrev=False)
    parser.add_argument("--schema", required=True, metavar=schema.SCHEMA_FILENAME)
    try:
        args = parser.parse_args(argv)
        snapshot = schema.read_schema(schema.path_parts(args.schema, schema.SCHEMA_FILENAME))
        raw = sys.stdin.buffer.read(MAX_SQL_BYTES + 1)
        if len(raw) > MAX_SQL_BYTES:
            raise ValueError()
        report = extract_dependencies(raw.decode("utf-8"), snapshot["columns"])
    except (OSError, ValueError, RecursionError, NotImplementedError):
        print("ERROR: invalid SQL dependency input or schema", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 2 if report["status"] == "UNRESOLVED" else 0


if __name__ == "__main__":
    sys.exit(main())
