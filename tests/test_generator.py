"""Generator tests with a mocked HTTP layer: provider selection, requests, errors, parsing."""

import json

import pytest
import requests

from text2sql import generator
from text2sql.generator import GenerationError, describe_model, generate_sql, get_provider

SETTINGS = ("TEXT2SQL_PROVIDER", "GROQ_API_KEY", "GROQ_MODEL", "OLLAMA_URL", "OLLAMA_MODEL")
REPLY = json.dumps({"sql": "SELECT * FROM employees;", "explanation": "All employees."})


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for key in SETTINGS:
        monkeypatch.delenv(key, raising=False)


class FakeResponse:
    def __init__(self, status_code=200, body=None, text=None):
        self.status_code = status_code
        self.ok = status_code < 400
        self._body = body
        self.text = text if text is not None else json.dumps(body)

    def json(self):
        if self._body is None:
            raise requests.JSONDecodeError("bad", self.text, 0)
        return self._body


class FakePost:
    """Stands in for requests.post: returns `response` (or raises `error`) and records calls."""

    def __init__(self):
        self.response = None
        self.error = None
        self.calls = []

    def __call__(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.error:
            raise self.error
        return self.response


@pytest.fixture
def post(monkeypatch):
    fake = FakePost()
    monkeypatch.setattr(generator.requests, "post", fake)
    return fake


def groq_body(content):
    return {"choices": [{"message": {"content": content}}]}


def ollama_body(content):
    return {"message": {"content": content}}


# ---------- provider selection ----------

def test_defaults_to_ollama_without_settings():
    assert get_provider() == "ollama"
    assert describe_model() == "Ollama · llama3.2:3b"


def test_groq_api_key_selects_groq(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    assert get_provider() == "groq"
    assert describe_model() == "Groq · openai/gpt-oss-120b"


def test_blank_groq_api_key_keeps_ollama(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "  ")
    assert get_provider() == "ollama"


def test_explicit_provider_wins_over_key(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setenv("TEXT2SQL_PROVIDER", "Ollama")
    assert get_provider() == "ollama"


def test_unknown_provider_is_a_clear_error(monkeypatch):
    monkeypatch.setenv("TEXT2SQL_PROVIDER", "openai")
    with pytest.raises(GenerationError, match="Unknown TEXT2SQL_PROVIDER"):
        get_provider()
    assert describe_model() == "not configured"


def test_groq_without_key_is_a_clear_error(monkeypatch, post):
    monkeypatch.setenv("TEXT2SQL_PROVIDER", "groq")
    with pytest.raises(GenerationError, match="GROQ_API_KEY is not set"):
        generate_sql("q", "schema")
    assert post.calls == []


def test_model_overrides(monkeypatch):
    monkeypatch.setenv("OLLAMA_MODEL", "qwen2.5-coder:3b")
    assert describe_model() == "Ollama · qwen2.5-coder:3b"
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setenv("GROQ_MODEL", "openai/gpt-oss-20b")
    assert describe_model() == "Groq · openai/gpt-oss-20b"


# ---------- requests ----------

def test_groq_request_and_reply(monkeypatch, post):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    post.response = FakeResponse(body=groq_body(REPLY))

    generation = generate_sql("Show all employees", "Table employees")

    assert generation.sql == "SELECT * FROM employees"
    assert generation.explanation == "All employees."
    url, kwargs = post.calls[0]
    assert url == "https://api.groq.com/openai/v1/chat/completions"
    assert kwargs["headers"] == {"Authorization": "Bearer test-key"}
    assert kwargs["json"]["model"] == "openai/gpt-oss-120b"
    assert kwargs["json"]["response_format"] == {"type": "json_object"}
    assert "Show all employees" in kwargs["json"]["messages"][1]["content"]


def test_ollama_request_and_reply(monkeypatch, post):
    monkeypatch.setenv("OLLAMA_URL", "http://ollama:11434/")
    post.response = FakeResponse(body=ollama_body(REPLY))

    assert generate_sql("Show all employees", "Table employees").sql == "SELECT * FROM employees"
    url, kwargs = post.calls[0]
    assert url == "http://ollama:11434/api/chat"
    assert kwargs["json"]["model"] == "llama3.2:3b"
    assert "headers" not in kwargs


# ---------- errors ----------

@pytest.mark.parametrize("status, message", [
    (401, "rejected the API key"),
    (404, "model 'openai/gpt-oss-120b' was not found"),
    (429, "rate limit"),
    (500, "Groq returned HTTP 500"),
])
def test_groq_http_errors(monkeypatch, post, status, message):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    post.response = FakeResponse(status, body={"error": {"message": "x"}})
    with pytest.raises(GenerationError, match=message):
        generate_sql("q", "schema")


def test_ollama_missing_model(post):
    post.response = FakeResponse(404, body={"error": "model not found"})
    with pytest.raises(GenerationError, match="ollama pull llama3.2:3b"):
        generate_sql("q", "schema")


@pytest.mark.parametrize("error, message", [
    (requests.ConnectionError(), "Could not reach Ollama"),
    (requests.Timeout(), "longer than"),
    (requests.exceptions.InvalidURL("bad url"), "Request to the LLM failed"),
])
def test_network_errors(post, error, message):
    post.error = error
    with pytest.raises(GenerationError, match=message):
        generate_sql("q", "schema")


@pytest.mark.parametrize("response", [
    FakeResponse(body=None, text="<html>proxy error</html>"),   # not JSON
    FakeResponse(body={"unexpected": True}),                    # missing keys
    FakeResponse(body={"choices": []}),                         # empty list
])
def test_groq_malformed_responses(monkeypatch, post, response):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    post.response = response
    with pytest.raises(GenerationError, match="unexpected response"):
        generate_sql("q", "schema")


@pytest.mark.parametrize("content", ["", "   ", None])
def test_empty_reply(post, content):
    post.response = FakeResponse(body=ollama_body(content))
    with pytest.raises(GenerationError, match="empty reply"):
        generate_sql("q", "schema")


# ---------- parsing ----------

@pytest.mark.parametrize("raw, sql, explanation", [
    ('{"sql": null, "explanation": "Cannot delete data."}', "", "Cannot delete data."),
    ('{"explanation": "No such column."}', "", "No such column."),
    ('{"sql": "SELECT 1", "explanation": null}', "SELECT 1", ""),
    ('{"sql": "```sql\\nSELECT 1;\\n```", "explanation": ""}', "SELECT 1", ""),
    ("```sql\nSELECT 1;\n```", "SELECT 1", ""),
])
def test_parse_response(raw, sql, explanation):
    generation = generator._parse_response(raw)
    assert (generation.sql, generation.explanation) == (sql, explanation)


@pytest.mark.parametrize("raw", ['["SELECT 1"]', '"SELECT 1"', "42"])
def test_parse_response_rejects_non_object_json(raw):
    with pytest.raises(GenerationError, match="unexpected shape"):
        generator._parse_response(raw)
