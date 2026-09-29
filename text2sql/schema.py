"""Read a SQLite database's structure so the LLM knows what it can query."""

from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path

from text2sql.executor import connect_read_only

EXAMPLE_VALUES_PER_COLUMN = 3


@dataclass
class Column:
    name: str
    type: str
    primary_key: bool = False
    references: str | None = None   # "table.column" when it is a foreign key
    examples: list[str] = field(default_factory=list)


@dataclass
class Table:
    name: str
    row_count: int
    columns: list[Column]


def read_schema(db_path: str | Path) -> list[Table]:
    """Return every user table with its columns, keys and a few example values."""
    with closing(connect_read_only(db_path)) as conn:
        table_names = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]

        tables = []
        for table in table_names:
            quoted = _quote(table)
            foreign_keys = {
                fk[3]: f"{fk[2]}.{fk[4]}"   # from_column -> "table.to_column"
                for fk in conn.execute(f"PRAGMA foreign_key_list({quoted})")
            }
            columns = []
            for _, name, col_type, _, _, pk in conn.execute(f"PRAGMA table_info({quoted})"):
                column = Column(name, col_type or "ANY", bool(pk), foreign_keys.get(name))
                # Example values help the model match text exactly, e.g. 'Marketing'.
                if "TEXT" in column.type.upper() and not column.primary_key:
                    column.examples = [
                        str(value)[:40]
                        for (value,) in conn.execute(
                            f"SELECT DISTINCT {_quote(name)} FROM {quoted} "
                            f"WHERE {_quote(name)} IS NOT NULL LIMIT {EXAMPLE_VALUES_PER_COLUMN}"
                        )
                    ]
                columns.append(column)

            row_count = conn.execute(f"SELECT COUNT(*) FROM {quoted}").fetchone()[0]
            tables.append(Table(table, row_count, columns))
    return tables


def schema_to_text(tables: list[Table]) -> str:
    """Compact, LLM-friendly description of the schema."""
    lines = []
    for table in tables:
        lines.append(f"Table {table.name} ({table.row_count} rows)")
        for col in table.columns:
            line = f"  - {col.name} {col.type}"
            if col.primary_key:
                line += " PRIMARY KEY"
            if col.references:
                line += f" -> references {col.references}"
            if col.examples:
                line += "  e.g. " + ", ".join(f"'{v}'" for v in col.examples)
            lines.append(line)
        lines.append("")
    return "\n".join(lines).strip()


def table_names(tables: list[Table]) -> set[str]:
    return {table.name.lower() for table in tables}


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'
