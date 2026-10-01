"""Check that generated SQL is a single, read-only SELECT before it runs.

Uses sqlglot to parse the SQL into a syntax tree, so the checks are based on
what the statement actually is, not on searching for keywords in the text.
"""

import logging
import re
from dataclasses import dataclass

import sqlglot
from sqlglot import exp

# sqlglot logs a warning for statements it can't fully parse; we reject those anyway.
logging.getLogger("sqlglot").setLevel(logging.ERROR)

# Statement types that can change data, schema, or the connection.
FORBIDDEN_NODES = (
    exp.Insert, exp.Update, exp.Delete, exp.Merge,
    exp.Create, exp.Drop, exp.Alter,
    exp.Attach, exp.Detach, exp.Pragma,
    exp.Transaction, exp.Commit, exp.Rollback,
    exp.Command,   # anything sqlglot doesn't understand (VACUUM, REPLACE, ...)
)

# load_extension can run native code; randomblob/zeroblob can allocate huge values in one call.
FORBIDDEN_FUNCTIONS = {"load_extension", "randomblob", "zeroblob"}

# Table-valued pragma functions, e.g. pragma_table_info('x'), pragma_database_list.
FORBIDDEN_FUNCTION_PREFIX = "pragma_"

# printf()/format() accept a width or precision that can build a huge string, e.g.
# printf('%.*c', 1000000000, 'x'). Allow normal use like printf('%.2f', x), block `*` and 1000+.
FORMAT_FUNCTIONS = {"printf", "format"}
LARGE_FORMAT_SPEC = re.compile(r"%[-+ 0#,!]*(?:\*|\d{4,}|\d*\.(?:\*|\d{4,}))")


@dataclass
class ValidationResult:
    ok: bool
    message: str


def validate_sql(sql: str, allowed_tables: set[str]) -> ValidationResult:
    if not sql or not sql.strip():
        return ValidationResult(False, "No SQL to run.")

    try:
        statements = [s for s in sqlglot.parse(sql, read="sqlite") if s is not None]
    except sqlglot.errors.ParseError as e:
        return ValidationResult(False, f"SQL could not be parsed: {e}")

    if len(statements) != 1:
        return ValidationResult(False, f"Exactly one statement is allowed, found {len(statements)}.")
    statement = statements[0]

    # Root must be a query: SELECT, WITH ... SELECT, or UNION/INTERSECT/EXCEPT of SELECTs.
    if not isinstance(statement, exp.Query):
        kind = statement.key.upper()
        return ValidationResult(False, f"Only SELECT queries are allowed, got {kind}.")

    for node in statement.walk():
        if isinstance(node, FORBIDDEN_NODES):
            return ValidationResult(False, f"Forbidden operation inside query: {node.key.upper()}.")
        if isinstance(node, exp.Func):
            name = _function_name(node)
            if name in FORBIDDEN_FUNCTIONS or name.startswith(FORBIDDEN_FUNCTION_PREFIX):
                return ValidationResult(False, f"Function {name}() is not allowed.")
            if name in FORMAT_FUNCTIONS and not _is_safe_format(node):
                return ValidationResult(
                    False, f"{name}() is only allowed with a literal format and widths under 1000."
                )

    cte_names = {cte.alias_or_name.lower() for cte in statement.find_all(exp.CTE)}
    unknown = set()
    for table in statement.find_all(exp.Table):
        if table.db and table.db.lower() != "main":
            return ValidationResult(False, f"Access to database '{table.db}' is not allowed.")
        name = table.name.lower()
        if name and name not in allowed_tables and name not in cte_names:
            unknown.add(table.name)
    if unknown:
        available = ", ".join(sorted(allowed_tables))
        return ValidationResult(
            False, f"Unknown table(s): {', '.join(sorted(unknown))}. Available: {available}."
        )

    return ValidationResult(True, "Valid read-only SELECT on known tables.")


def _function_name(node: exp.Func) -> str:
    name = node.name if isinstance(node, exp.Anonymous) else node.sql_name()
    return name.lower()


def _is_safe_format(node: exp.Func) -> bool:
    """The format string must be a literal without `*` or 4+ digit width/precision."""
    fmt = node.this if isinstance(node, exp.Format) else (node.expressions or [None])[0]
    if not (isinstance(fmt, exp.Literal) and fmt.is_string):
        return False
    return not LARGE_FORMAT_SPEC.search(fmt.this)
