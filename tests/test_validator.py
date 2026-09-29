"""Safety tests: valid SELECTs pass, anything that could change data is blocked."""

import sqlite3

import pytest

from data.create_sample_db import create_sample_db
from text2sql.executor import ExecutionError, run_query
from text2sql.schema import read_schema, table_names
from text2sql.validator import validate_sql

TABLES = {"departments", "employees", "projects", "employee_projects"}


@pytest.mark.parametrize("sql", [
    "SELECT * FROM employees",
    "select first_name from Employees where salary > 50000",
    "SELECT e.first_name, d.name FROM employees e JOIN departments d ON e.department_id = d.id",
    "SELECT d.name, AVG(e.salary) FROM employees e JOIN departments d "
    "ON e.department_id = d.id GROUP BY d.name",
    "WITH rich AS (SELECT * FROM employees WHERE salary > 80000) SELECT COUNT(*) FROM rich",
    "SELECT name FROM departments UNION SELECT name FROM projects",
    "SELECT * FROM employees WHERE department_id IN (SELECT id FROM departments)",
    "SELECT 1 + 1",
])
def test_safe_selects_pass(sql):
    result = validate_sql(sql, TABLES)
    assert result.ok, result.message


@pytest.mark.parametrize("sql", [
    "DELETE FROM employees",
    "DROP TABLE employees",
    "UPDATE employees SET salary = 0",
    "INSERT INTO departments VALUES (99, 'X', 'Y')",
    "REPLACE INTO departments VALUES (1, 'X', 'Y')",
    "CREATE TABLE hacked (id INTEGER)",
    "ALTER TABLE employees ADD COLUMN x TEXT",
    "PRAGMA writable_schema = ON",
    "ATTACH DATABASE 'other.db' AS other",
    "VACUUM",
    "SELECT * FROM employees; DROP TABLE employees",
    "SELECT load_extension('evil.dll')",
    "SELECT * FROM other.secrets",
    "SELECT * FROM passwords",
    "",
    "this is not sql",
])
def test_unsafe_or_invalid_sql_is_blocked(sql):
    result = validate_sql(sql, TABLES)
    assert not result.ok


def test_unknown_table_message_lists_available_tables():
    result = validate_sql("SELECT * FROM staff", TABLES)
    assert "staff" in result.message and "employees" in result.message


@pytest.fixture
def sample_db(tmp_path):
    return create_sample_db(tmp_path / "company.db")


def test_schema_is_read_from_database(sample_db):
    tables = read_schema(sample_db)
    assert table_names(tables) == TABLES
    employees = next(t for t in tables if t.name == "employees")
    dept_col = next(c for c in employees.columns if c.name == "department_id")
    assert dept_col.references == "departments.id"


def test_executor_returns_rows(sample_db):
    result = run_query(sample_db, "SELECT COUNT(*) AS n FROM employees")
    assert result.dataframe["n"][0] == 22


def test_executor_is_read_only_even_without_validator(sample_db):
    with pytest.raises(ExecutionError):
        run_query(sample_db, "DELETE FROM employees")
    # Data is untouched.
    with sqlite3.connect(sample_db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM employees").fetchone()[0] == 22


def test_executor_truncates_large_results(sample_db):
    result = run_query(sample_db, "SELECT * FROM employees", max_rows=5)
    assert len(result.dataframe) == 5 and result.truncated
