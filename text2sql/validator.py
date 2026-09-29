"""Check that generated SQL is a single, read-only SELECT before it runs.

Uses sqlglot to parse the SQL into a syntax tree, so the checks are based on
what the statement actually is, not on searching for keywords in the text.
"""

import logging
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

FORBIDDEN_FUNCTIONS = {"load_extension"}


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
        if isinstance(node, exp.Func) and _function_name(node) in FORBIDDEN_FUNCTIONS:
            return ValidationResult(False, f"Function {_function_name(node)}() is not allowed.")

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
