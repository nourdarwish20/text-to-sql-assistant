"""Run a (validated) SELECT on SQLite with a read-only connection.

This is the second safety layer: even if a harmful statement slipped past the
validator, the connection itself refuses to write.
"""

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

MAX_ROWS = 500
TIMEOUT_SECONDS = 5


class ExecutionError(Exception):
    """SQLite rejected the query or it ran too long."""


@dataclass
class QueryResult:
    dataframe: pd.DataFrame
    truncated: bool       # True if there were more than MAX_ROWS rows
    elapsed_ms: float


def connect_read_only(db_path: str | Path) -> sqlite3.Connection:
    """Open the database file in read-only mode (writes raise an error)."""
    path = Path(db_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Database not found: {path}")
    conn = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
    conn.execute("PRAGMA query_only = ON")
    return conn


def run_query(
    db_path: str | Path,
    sql: str,
    max_rows: int = MAX_ROWS,
    timeout: float = TIMEOUT_SECONDS,
) -> QueryResult:
    conn = connect_read_only(db_path)

    # SQLite calls this handler periodically; returning non-zero aborts the query.
    deadline = time.monotonic() + timeout
    conn.set_progress_handler(lambda: int(time.monotonic() > deadline), 10_000)

    start = time.perf_counter()
    try:
        cursor = conn.execute(sql)
        rows = cursor.fetchmany(max_rows + 1)
        columns = [col[0] for col in cursor.description or []]
    except sqlite3.OperationalError as e:
        if "interrupted" in str(e):
            raise ExecutionError(f"Query took longer than {timeout}s and was stopped.") from e
        raise ExecutionError(f"SQLite error: {e}") from e
    except sqlite3.Error as e:
        raise ExecutionError(f"SQLite error: {e}") from e
    finally:
        conn.close()
    elapsed_ms = (time.perf_counter() - start) * 1000

    truncated = len(rows) > max_rows
    df = pd.DataFrame(rows[:max_rows], columns=_unique(columns))
    return QueryResult(dataframe=df, truncated=truncated, elapsed_ms=elapsed_ms)


def _unique(names: list[str]) -> list[str]:
    """Rename duplicate column names (e.g. two `name` columns from a JOIN)."""
    seen: dict[str, int] = {}
    result = []
    for name in names:
        seen[name] = seen.get(name, 0) + 1
        result.append(name if seen[name] == 1 else f"{name}_{seen[name]}")
    return result
