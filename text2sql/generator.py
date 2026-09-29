"""Turn a natural-language question into SQL with an LLM.

This is the ONLY file that knows which LLM provider is used. The rest of the
app calls `generate_sql()` and gets back a `Generation`.

Default provider: Ollama (free, runs locally). Change the model with the
TEXT2SQL_MODEL environment variable. To switch to another provider (a hosted
API, llama.cpp, ...), rewrite `_call_llm()` - nothing else needs to change.
"""

import json
import os
import re
from dataclasses import dataclass

import requests

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434").rstrip("/")
MODEL = os.getenv("TEXT2SQL_MODEL", "llama3.2:3b")
REQUEST_TIMEOUT_SECONDS = 180

SYSTEM_PROMPT = """You are an expert SQLite analyst. You translate questions into ONE SQLite SELECT query.

Rules:
- Use only the tables and columns listed in the schema. Never invent names.
- Join tables using the "references" relationships shown in the schema.
- When filtering on text, use the exact spelling from the example values if one matches.
  Otherwise compare case-insensitively, e.g. LOWER(col) = 'value' or col LIKE '%value%'.
- Return readable columns (names, not only ids) and give computed columns clear aliases.
- Do not add a LIMIT unless the question asks for a specific number of rows.
- If the question asks to insert, update, delete, or change anything, or cannot be answered
  from the schema, return an empty "sql" and explain why in "explanation".

Reply with JSON only: {"sql": "<query>", "explanation": "<one short sentence>"}"""

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "sql": {"type": "string"},
        "explanation": {"type": "string"},
    },
    "required": ["sql", "explanation"],
}


class GenerationError(Exception):
    """The LLM could not be reached or returned something unusable."""


@dataclass
class Generation:
    sql: str
    explanation: str


def describe_model() -> str:
    return f"Ollama · {MODEL}"


def generate_sql(question: str, schema_text: str) -> Generation:
    user_prompt = f"Database schema:\n{schema_text}\n\nQuestion: {question.strip()}"
    raw = _call_llm(SYSTEM_PROMPT, user_prompt)
    return _parse_response(raw)


def _call_llm(system_prompt: str, user_prompt: str) -> str:
    """Send the prompt to the LLM and return its raw text reply. Swap this to change provider."""
    try:
        response = requests.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": MODEL,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "format": RESPONSE_SCHEMA,       # Ollama structured output: forces this JSON shape
                "stream": False,
                "options": {"temperature": 0},  # deterministic: same question -> same SQL
            },
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except requests.ConnectionError as e:
        raise GenerationError(
            f"Could not reach Ollama at {OLLAMA_URL}. Is it running? Start the Ollama app "
            "or run `ollama serve`."
        ) from e
    except requests.Timeout as e:
        raise GenerationError(f"The model took longer than {REQUEST_TIMEOUT_SECONDS}s to answer.") from e

    if response.status_code == 404:
        raise GenerationError(f"Model '{MODEL}' is not installed. Run: ollama pull {MODEL}")
    if not response.ok:
        raise GenerationError(f"Ollama returned HTTP {response.status_code}: {response.text[:300]}")
    return response.json()["message"]["content"]


def _parse_response(raw: str) -> Generation:
    """Extract SQL + explanation from the model reply, tolerating small format slips."""
    try:
        data = json.loads(raw)
        sql, explanation = str(data.get("sql", "")), str(data.get("explanation", ""))
    except (json.JSONDecodeError, AttributeError):
        # Fall back to a ```sql fenced block or the raw text.
        match = re.search(r"```(?:sql)?\s*(.+?)```", raw, re.DOTALL | re.IGNORECASE)
        sql, explanation = (match.group(1) if match else raw), ""

    sql = re.sub(r"^```(?:sql)?|```$", "", sql.strip(), flags=re.IGNORECASE).strip()
    sql = sql.rstrip(";").strip()
    return Generation(sql=sql, explanation=explanation.strip())
