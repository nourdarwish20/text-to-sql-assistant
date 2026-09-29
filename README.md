# 🗄️ Text-to-SQL Assistant

Ask a question about a SQLite database in plain English and get the answer as a table.
The app writes the SQL with a **free, local LLM**, checks that the SQL is a **safe
read-only SELECT**, runs it, and shows the SQL next to the result so you can see what it did.

> "Show all employees in the marketing department"
> → `SELECT e.first_name, e.last_name, e.job_title FROM employees e JOIN departments d ON e.department_id = d.id WHERE d.name = 'Marketing'`
> → a table with 4 employees

## How it works

```
question ──► schema.py ──► generator.py ──► validator.py ──► executor.py ──► table in the UI
             read tables    LLM writes SQL   single SELECT?   read-only
             & columns      (Ollama, local)  known tables?    connection,
                                             no DDL/DML?      row + time limits
```

**Two layers of safety:**
1. **Validator:** the SQL is parsed into a syntax tree with [sqlglot](https://github.com/tobymao/sqlglot).
   Only one statement is allowed, and it must be a query (`SELECT`, `WITH … SELECT`, `UNION` …).
   Any `INSERT/UPDATE/DELETE/DROP/CREATE/ALTER/ATTACH/PRAGMA`, `load_extension()`, or
   unknown table is rejected before anything runs.
2. **Executor:** the database is opened with `mode=ro` and `PRAGMA query_only`, so SQLite itself
   refuses writes even if something got past the validator. Queries are capped at 500 rows
   and stopped after 5 seconds.

## Quick start

**1. Install [Ollama](https://ollama.com/download)** and download the model (~2 GB, one time):
```bash
ollama pull llama3.2:3b
```

**2. Install the Python packages** (Python 3.10+):
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

**Run the tests:**
```bash
python -m pytest
```

## Try these questions

| Type | Question |
|---|---|
| Simple | Show all employees in the marketing department |
| JOIN | List each project with its department name |
| Aggregate | What is the average salary per department? |
| Multi-table | Which employees work on more than one project? |
| Blocked | Paste `DROP TABLE employees` into "Write or edit SQL yourself" |

## Sample database

`data/company.db` is a small company with 4 related tables:

- `departments`: 6 departments (Engineering, Marketing, Sales, …)
- `employees`: 22 employees with job title, salary, hire date, department
- `projects`: 7 projects with budget, dates, owning department
- `employee_projects`: who works on which project and in what role

To use your own database, drop any `.db` file into `data/` and pick it in the sidebar.

## Choosing the model

The LLM is isolated in `text2sql/generator.py`; no other file knows which provider is used.

- **Change the model:** copy `.env.example` to `.env` and set `TEXT2SQL_MODEL` to any
  model from `ollama list`, for example the code-specialised `qwen2.5-coder:3b`, or
  `qwen2.5-coder:7b` (more accurate, ~4.7 GB, slower on CPU).
- **Change the provider** (a hosted API, llama.cpp, …): rewrite the one function `_call_llm()`
  in `generator.py` so it returns the model's text reply. The prompt, parsing, validation
  and UI stay the same.

## Project structure

```
app.py                     Streamlit UI
text2sql/
  schema.py                reads tables, columns, keys and example values from SQLite
  generator.py             builds the prompt and calls the LLM (only provider-specific file)
  validator.py             sqlglot-based safety checks
  executor.py              read-only execution with row and time limits
data/create_sample_db.py   builds the sample database
tests/test_validator.py    safety, schema and executor tests (no LLM needed)
```

## Limitations

- Small local models can misread ambiguous questions. The generated SQL is always shown so
  you can check it, and you can edit it and run it again.
- Only SQLite is supported.
