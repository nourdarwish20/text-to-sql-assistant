"""Streamlit interface: ask a question, see the SQL, the safety check and the result.

Run with:  python -m streamlit run app.py
"""

import os
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

from data.create_sample_db import create_sample_db
from text2sql.executor import MAX_ROWS, ExecutionError, run_query
from text2sql.generator import GenerationError, describe_model, generate_sql
from text2sql.schema import read_schema, schema_to_text, table_names
from text2sql.validator import validate_sql

DATA_DIR = Path(__file__).parent / "data"
SAMPLE_DB = DATA_DIR / "company.db"

# Settings generator.py reads from the environment; they may also come from Streamlit secrets.
SETTINGS = ("TEXT2SQL_PROVIDER", "GROQ_API_KEY", "GROQ_MODEL", "OLLAMA_URL", "OLLAMA_MODEL")

EXAMPLE_QUESTIONS = [
    "Show all employees in the marketing department",
    "List each project with its department name",
    "What is the average salary per department?",
    "Which employees work on more than one project?",
]


def load_settings() -> None:
    """Read .env, then copy any Streamlit secrets into the environment (env vars win)."""
    load_dotenv()
    try:
        secrets = dict(st.secrets)
    except FileNotFoundError:   # no secrets.toml: fine locally
        return
    for key in SETTINGS:
        if key in secrets and not os.getenv(key):
            os.environ[key] = str(secrets[key])


st.set_page_config(page_title="Text-to-SQL", page_icon="🗄️", layout="wide")
load_settings()

if not SAMPLE_DB.exists():
    create_sample_db(SAMPLE_DB)


@st.cache_data
def load_schema(db_path: str, modified: float):
    """Cached per file + modification time, so edits to the DB are picked up."""
    return read_schema(db_path)


def run_sql(sql: str, db_path: Path, allowed_tables: set[str]) -> dict:
    """Validate and run one SQL statement; the caller keeps the outcome in session state."""
    outcome = {"sql": sql, "check": validate_sql(sql, allowed_tables), "result": None, "error": None}
    if outcome["check"].ok:
        try:
            outcome["result"] = run_query(db_path, sql)
        except ExecutionError as e:
            outcome["error"] = str(e)
    return outcome


def show_outcome(outcome: dict) -> None:
    st.markdown("**SQL**")
    st.code(outcome["sql"], language="sql")

    check = outcome["check"]
    if not check.ok:
        st.error(f"🚫 Blocked by validator: {check.message}")
        return
    st.success(f"✅ {check.message}")

    if outcome["error"]:
        st.error(outcome["error"])
        return

    result = outcome["result"]
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
    "Type a question in plain English. The app writes SQL with an LLM, checks it is a "
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
    generated = {"error": None, "explanation": "", "outcome": None}
    with st.spinner(f"Writing SQL with {describe_model()}…"):
        try:
            generation = generate_sql(question, schema_text)
        except GenerationError as e:
            generated["error"] = str(e)
    if not generated["error"]:
        generated["explanation"] = generation.explanation
        if generation.sql:
            generated["outcome"] = run_sql(generation.sql, db_path, allowed_tables)
            st.session_state.manual_sql = generation.sql   # ready to edit below
    st.session_state.generated = generated

# Results live in session state, so they survive reruns (e.g. clicking another button).
if generated := st.session_state.get("generated"):
    if generated["error"]:
        st.error(generated["error"])
    else:
        if generated["explanation"]:
            st.info(generated["explanation"])
        if generated["outcome"]:
            show_outcome(generated["outcome"])
        else:
            st.warning("The model did not return a SQL query for this question.")

with st.expander("Write or edit SQL yourself"):
    manual_sql = st.text_area("SQL", height=120, key="manual_sql")
    if st.button("Validate & run") and manual_sql.strip():
        st.session_state.manual = run_sql(manual_sql, db_path, allowed_tables)
    if manual := st.session_state.get("manual"):
        show_outcome(manual)
