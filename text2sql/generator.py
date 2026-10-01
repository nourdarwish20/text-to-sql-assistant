"""Turn a natural-language question into SQL with an LLM.

This is the ONLY file that knows which LLM provider is used. The rest of the
app calls `generate_sql()` and gets back a `Generation`.

Providers:
- Ollama (default): free, runs locally. Model set with OLLAMA_MODEL.
- Groq (hosted): used when GROQ_API_KEY is set, e.g. on Streamlit Community Cloud.
  Model set with GROQ_MODEL.
Set TEXT2SQL_PROVIDER=ollama or groq to choose explicitly.

Settings are read from environment variables on every call, so a key added via
.env or Streamlit secrets is picked up without code changes.
"""

import json
import os
import re
from dataclasses import dataclass

import requests

PROVIDERS = ("ollama", "groq")
DEFAULT_OLLAMA_URL = "http://localhost:11434"
DEFAULT_OLLAMA_MODEL = "llama3.2:3b"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_GROQ_MODEL = "openai/gpt-oss-120b"
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


def get_provider() -> str:
    """TEXT2SQL_PROVIDER if set, otherwise Groq when GROQ_API_KEY exists, otherwise Ollama."""
    provider = os.getenv("TEXT2SQL_PROVIDER", "").strip().lower()
    if not provider:
        return "groq" if os.getenv("GROQ_API_KEY", "").strip() else "ollama"
    if provider not in PROVIDERS:
        raise GenerationError(
            f"Unknown TEXT2SQL_PROVIDER '{provider}'. Use one of: {', '.join(PROVIDERS)}."
        )
    return provider


def describe_model() -> str:
    try:
        provider = get_provider()
    except GenerationError:
        return "not configured"
    if provider == "groq":
        return f"Groq · {_groq_model()}"
    return f"Ollama · {_ollama_model()}"


def generate_sql(question: str, schema_text: str) -> Generation:
    user_prompt = f"Database schema:\n{schema_text}\n\nQuestion: {question.strip()}"
    raw = _call_llm(SYSTEM_PROMPT, user_prompt)
    return _parse_response(raw)


def _call_llm(system_prompt: str, user_prompt: str) -> str:
    """Send the prompt to the configured LLM and return its raw text reply."""
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    if get_provider() == "groq":
        return _call_groq(messages)
    return _call_ollama(messages)


def _ollama_url() -> str:
    return os.getenv("OLLAMA_URL", DEFAULT_OLLAMA_URL).strip().rstrip("/")


def _ollama_model() -> str:
    return os.getenv("OLLAMA_MODEL", "").strip() or DEFAULT_OLLAMA_MODEL


def _groq_model() -> str:
    return os.getenv("GROQ_MODEL", "").strip() or DEFAULT_GROQ_MODEL


def _call_ollama(messages: list[dict]) -> str:
    url, model = _ollama_url(), _ollama_model()
    response = _post(
        f"{url}/api/chat",
        json={
            "model": model,
            "messages": messages,
            "format": RESPONSE_SCHEMA,       # Ollama structured output: forces this JSON shape
            "stream": False,
            "options": {"temperature": 0},  # deterministic: same question -> same SQL
        },
        unreachable=f"Could not reach Ollama at {url}. Is it running? Start the Ollama app "
        "or run `ollama serve`.",
    )
    if response.status_code == 404:
        raise GenerationError(f"Model '{model}' is not installed. Run: ollama pull {model}")
    if not response.ok:
        raise GenerationError(f"Ollama returned HTTP {response.status_code}: {response.text[:300]}")
    return _extract(response, lambda data: data["message"]["content"], "Ollama")


def _call_groq(messages: list[dict]) -> str:
    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not api_key:
        raise GenerationError(
            "TEXT2SQL_PROVIDER is 'groq' but GROQ_API_KEY is not set. Add it to .env "
            "or to the app's Streamlit secrets."
        )
    model = _groq_model()
    response = _post(
        GROQ_URL,
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": model,
            "messages": messages,
            "response_format": {"type": "json_object"},   # JSON mode: reply is a JSON object
            "temperature": 0,
        },
        unreachable="Could not reach the Groq API. Check your internet connection.",
    )
    if response.status_code == 401:
        raise GenerationError("Groq rejected the API key (HTTP 401). Check GROQ_API_KEY.")
    if response.status_code == 404:
        raise GenerationError(f"Groq model '{model}' was not found. Check GROQ_MODEL.")
    if response.status_code == 429:
        raise GenerationError("Groq rate limit reached (HTTP 429). Wait a moment and try again.")
    if not response.ok:
        raise GenerationError(f"Groq returned HTTP {response.status_code}: {response.text[:300]}")
    return _extract(response, lambda data: data["choices"][0]["message"]["content"], "Groq")


def _post(url: str, unreachable: str, **kwargs) -> requests.Response:
    try:
        return requests.post(url, timeout=REQUEST_TIMEOUT_SECONDS, **kwargs)
    except requests.ConnectionError as e:
        raise GenerationError(unreachable) from e
    except requests.Timeout as e:
        raise GenerationError(f"The model took longer than {REQUEST_TIMEOUT_SECONDS}s to answer.") from e
    except requests.RequestException as e:
        raise GenerationError(f"Request to the LLM failed: {e}") from e


def _extract(response: requests.Response, get_content, provider: str) -> str:
    """Pull the reply text out of the provider's JSON, with a clear error if the shape is wrong."""
    try:
        content = get_content(response.json())
    except (ValueError, KeyError, IndexError, TypeError) as e:
        raise GenerationError(f"{provider} returned an unexpected response: {response.text[:300]}") from e
    if not isinstance(content, str) or not content.strip():
        raise GenerationError(f"{provider} returned an empty reply.")
    return content


def _parse_response(raw: str) -> Generation:
    """Extract SQL + explanation from the model reply, tolerating small format slips."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # Not JSON: fall back to a ```sql fenced block or the raw text.
        match = re.search(r"```(?:sql)?\s*(.+?)```", raw, re.DOTALL | re.IGNORECASE)
        sql, explanation = (match.group(1) if match else raw), ""
    else:
        if not isinstance(data, dict):
            raise GenerationError("The model replied with JSON in an unexpected shape.")
        sql, explanation = data.get("sql"), data.get("explanation")
        # A null or missing "sql" means the model chose not to write a query.
        sql = sql if isinstance(sql, str) else ""
        explanation = explanation if isinstance(explanation, str) else ""

    sql = re.sub(r"^```(?:sql)?|```$", "", sql.strip(), flags=re.IGNORECASE).strip()
    sql = sql.rstrip(";").strip()
    return Generation(sql=sql, explanation=explanation.strip())
