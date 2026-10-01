# 🗄️ Text-to-SQL Assistant

Ask a question about a SQLite database in plain English and get the answer as a table.
The app writes the SQL with an LLM (**local Ollama** by default, or **hosted Groq** when
deployed), checks that the SQL is a **safe read-only SELECT**, runs it, and shows the SQL next
to the result so you can see what it did.

> "Show all employees in the marketing department"
> → `SELECT e.first_name, e.last_name, e.job_title FROM employees e JOIN departments d ON e.department_id = d.id WHERE d.name = 'Marketing'`
> → a table with 4 employees

## How it works

```
question ──► schema.py ──► generator.py ──► validator.py ──► executor.py ──► table in the UI
             read tables    LLM writes SQL   single SELECT?   read-only
             & columns      (Ollama or Groq) known tables?    connection,
                                             no DDL/DML?      row, time and
                                             no risky funcs?  size limits
```

**Two layers of safety:**
1. **Validator:** the SQL is parsed into a syntax tree with [sqlglot](https://github.com/tobymao/sqlglot).
   Only one statement is allowed, and it must be a query (`SELECT`, `WITH … SELECT`, `UNION` …).
   These are rejected before anything runs:
   - `INSERT/UPDATE/DELETE/REPLACE/DROP/CREATE/ALTER/ATTACH/PRAGMA/VACUUM`
   - pragma table functions such as `pragma_table_info()`
   - `load_extension()`
   - memory-heavy calls: `randomblob()`, `zeroblob()`, and `printf()/format()` with a `*` or
     1000+ width (normal use like `printf('%.2f', x)` is fine)
   - tables that aren't in the database
2. **Executor:** the database is opened with `mode=ro` and `PRAGMA query_only`, so SQLite itself
   refuses writes even if something got past the validator. Queries are capped at 500 rows,
   stopped after 5 seconds, and no single value may exceed 10 MB.

## Quick start (local, with Ollama)

**1. Install [Ollama](https://ollama.com/download)** and download the model (~2 GB, one time):
```bash
ollama pull llama3.2:3b
```

**2. Install the Python packages** (Python 3.11+, 3.12 recommended):
```bash
python -m venv .venv
.venv\Scripts\activate          # Windows  (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt
```

**3. Run the app:**
```bash
python -m streamlit run app.py
```
It opens at http://localhost:8501. The sample database `data/company.db` is created
automatically on first run.

**Run the tests** (no LLM or API key needed; the LLM calls are mocked):
```bash
pytest
```

## Try these questions

| Type | Question |
|---|---|
| Simple | Show all employees in the marketing department |
| JOIN | List each project with its department name |
| Aggregate | What is the average salary per department? |
| Multi-table | Which employees work on more than one project? |
| Blocked | Paste `DROP TABLE employees` into "Write or edit SQL yourself" |

Generated SQL is copied into "Write or edit SQL yourself", so you can tweak it and run it again.

## Sample database

`data/company.db` is a small company with 4 related tables:

- `departments`: 6 departments (Engineering, Marketing, Sales, …)
- `employees`: 22 employees with job title, salary, hire date, department
- `projects`: 7 projects with budget, dates, owning department
- `employee_projects`: who works on which project and in what role

To use your own database locally, drop any `.db` file into `data/` and pick it in the sidebar.
(`.db` files are git-ignored, so a deployed app only has the sample database.)

## Choosing the LLM

The LLM is isolated in `text2sql/generator.py`; no other file knows which provider is used.
Settings come from environment variables, a `.env` file (copy `.env.example`), or Streamlit
secrets. Environment variables win over secrets.

| Setting | Default | Meaning |
|---|---|---|
| `TEXT2SQL_PROVIDER` | auto | `ollama` or `groq`. If unset: Groq when `GROQ_API_KEY` is set, otherwise Ollama |
| `OLLAMA_MODEL` | `llama3.2:3b` | Any model from `ollama list`, e.g. `qwen2.5-coder:3b` |
| `OLLAMA_URL` | `http://localhost:11434` | Where Ollama is listening |
| `GROQ_API_KEY` | (none) | Your key from [console.groq.com/keys](https://console.groq.com/keys) |
| `GROQ_MODEL` | `openai/gpt-oss-120b` | Any Groq chat model, e.g. `openai/gpt-oss-20b` (faster, less accurate) |

The model in use is shown in the sidebar. To add another provider, add a `_call_<name>()`
function in `generator.py` that returns the model's text reply.

## Deploy to Streamlit Community Cloud

1. Push this repository to GitHub.
2. Create a free API key at [console.groq.com/keys](https://console.groq.com/keys).
3. On [share.streamlit.io](https://share.streamlit.io), click **Create app**, pick the repo,
   branch `main` and main file `app.py`.
4. Open **Advanced settings**, choose **Python 3.12**, and paste into **Secrets**:
   ```toml
   GROQ_API_KEY = "gsk_..."
   # optional:
   # GROQ_MODEL = "openai/gpt-oss-120b"
   ```
5. Click **Deploy**. The sidebar should show `Model: Groq · openai/gpt-oss-120b`.

Never commit the key: `.env` and `.streamlit/secrets.toml` are git-ignored. To test the Groq
path locally, put `GROQ_API_KEY=...` in `.env` (or the TOML above in `.streamlit/secrets.toml`).

## Project structure

```
app.py                     Streamlit UI (reads .env / Streamlit secrets, keeps results in session state)
text2sql/
  schema.py                reads tables, columns, keys and example values from SQLite
  generator.py             builds the prompt and calls Ollama or Groq (only provider-specific file)
  validator.py             sqlglot-based safety checks
  executor.py              read-only execution with row, time and size limits
data/create_sample_db.py   builds the sample database
tests/test_validator.py    safety, schema and executor tests
tests/test_generator.py    provider selection, error handling and reply parsing (HTTP mocked)
.streamlit/config.toml     hides full tracebacks from visitors
pytest.ini                 lets plain `pytest` find the project modules
.python-version            Python version for local tools (pyenv, uv)
```

## Limitations

- Small local models can misread ambiguous questions. The generated SQL is always shown so
  you can check it, and you can edit it and run it again.
- With Groq, the question, the schema and a few example values per text column are sent to
  Groq's API. The free tier has rate limits; the app shows a clear message when one is hit.
- Only SQLite is supported.
