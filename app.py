"""Streamlit interface: ask a question, see the SQL, the safety check and the result.

Run with:  python -m streamlit run app.py
"""

from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

load_dotenv()  # read .env before generator.py reads its settings

from data.create_sample_db import create_sample_db  # noqa: E402
from text2sql.executor import MAX_ROWS, ExecutionError, run_query  # noqa: E402
from text2sql.generator import GenerationError, describe_model, generate_sql  # noqa: E402
from text2sql.schema import read_schema, schema_to_text, table_names  # noqa: E402
from text2sql.validator import validate_sql  # noqa: E402

DATA_DIR = Path(__file__).parent / "data"
SAMPLE_DB = DATA_DIR / "company.db"

EXAMPLE_QUESTIONS = [
    "Show all employees in the marketing department",
    "List each project with its department name",
    "What is the average salary per department?",
    "Which employees work on more than one project?",
]

st.set_page_config(page_title="Text-to-SQL", page_icon="🗄️", layout="wide")

if not SAMPLE_DB.exists():
    create_sample_db(SAMPLE_DB)


@st.cache_data
def load_schema(db_path: str, modified: float):
    """Cached per file + modification time, so edits to the DB are picked up."""
    return read_schema(db_path)


def show_query_result(sql: str, db_path: Path, allowed_tables: set[str]) -> None:
    """Validate, run and display one SQL statement."""
    st.markdown("**SQL**")
    st.code(sql, language="sql")

    check = validate_sql(sql, allowed_tables)
    if not check.ok:
        st.error(f"🚫 Blocked by validator: {check.message}")
        return
    st.success(f"✅ {check.message}")

    try:
        result = run_query(db_path, sql)
    except ExecutionError as e:
        st.error(str(e))
        return

    rows = len(result.dataframe)
    st.markdown(f"**Result** · {rows} row{'s' if rows != 1 else ''} · {result.elapsed_ms:.0f} ms")
    st.dataframe(result.dataframe, hide_index=True, width="stretch")
    if result.truncated:
        st.warning(f"Only the first {MAX_ROWS} rows are shown.")


# ---------- Sidebar: database + schema ----------
with st.sidebar:
    st.header("Database")
    databases = sorted(DATA_DIR.glob("*.db"))
    db_path = st.selectbox("SQLite file", databases, format_func=lambda p: p.name)
    tables = load_schema(str(db_path), db_path.stat().st_mtime)
    schema_text = schema_to_text(tables)
    allowed_tables = table_names(tables)

    st.caption(f"Model: {describe_model()}")
    st.subheader("Schema")
    for table in tables:
        with st.expander(f"{table.name} · {table.row_count} rows"):
            for col in table.columns:
                extra = " 🔑" if col.primary_key else ""
                extra += f" → {col.references}" if col.references else ""
                st.markdown(f"`{col.name}` {col.type}{extra}")

# ---------- Main: question -> SQL -> result ----------
st.title("🗄️ Ask your database")
st.caption(
    "Type a question in plain English. The app writes SQL with a local LLM, checks it is a "
    "safe read-only SELECT, runs it on SQLite, and shows the result."
)


def use_example(question: str) -> None:
    st.session_state.question = question


example_cols = st.columns(len(EXAMPLE_QUESTIONS))
for col, example in zip(example_cols, EXAMPLE_QUESTIONS):
    col.button(example, on_click=use_example, args=(example,), width="stretch")

question = st.text_input(
    "Your question", key="question", placeholder="e.g. Show all employees in the marketing department"
)

if st.button("Generate & run", type="primary") and question.strip():
    with st.spinner(f"Writing SQL with {describe_model()}…"):
        try:
            generation = generate_sql(question, schema_text)
        except GenerationError as e:
            st.error(str(e))
            st.stop()

    if generation.explanation:
        st.info(generation.explanation)
    if generation.sql:
        show_query_result(generation.sql, db_path, allowed_tables)
    else:
        st.warning("The model did not produce a query for this question.")

with st.expander("Write or edit SQL yourself"):
    manual_sql = st.text_area("SQL", height=120, key="manual_sql")
    if st.button("Validate & run") and manual_sql.strip():
        show_query_result(manual_sql, db_path, allowed_tables)
