import httpx
import pytest

from app.mcp.servers.search import web_search


def _run(monkeypatch, env, payload=None, exc=None):
    for k in ("SEARCH_API_BASE", "SEARCH_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)

    calls = []

    def fake_get(url, params=None, headers=None, timeout=None):
        calls.append({"url": url, "params": params, "headers": headers or {}, "timeout": timeout})
        if exc is not None:
            raise exc
        return httpx.Response(200, json=payload, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "get", fake_get)
    result = web_search("planner critic 规划", 3)
    return result, calls


def test_local_fallback_no_env(monkeypatch):
    monkeypatch.delenv("SEARCH_API_BASE", raising=False)
    monkeypatch.delenv("SEARCH_API_KEY", raising=False)
    result = web_search("planner critic 规划", 3)
    assert result["source"] == "local"
    assert result["count"] >= 1
    assert all(r["source"] == "local" for r in result["results"])
    assert all(r["url"].startswith("local://") for r in result["results"])
    assert result["result"]["ok"] is True
    assert result["server"] == "search"
    assert result["tool"] == "web_search"


def test_local_fallback_deterministic(monkeypatch):
    monkeypatch.delenv("SEARCH_API_BASE", raising=False)
    r1 = web_search("planner critic 规划", 3)
    r2 = web_search("planner critic 规划", 3)
    assert r1["results"] == r2["results"]


def test_web_success_serper_style(monkeypatch):
    payload = {
        "results": [
            {"title": "LangGraph Multi-Agent", "link": "https://example.com/a", "snippet": "planner critic reflector " * 3},
            {"title": "No URL item"},
            {"url": "https://example.com/b", "description": "RAG pgvector"},
        ]
    }
    result, calls = _run(monkeypatch, {"SEARCH_API_BASE": "https://api.example.com/search"}, payload)
    assert len(calls) == 1
    assert calls[0]["url"] == "https://api.example.com/search"
    assert calls[0]["params"]["q"] == "planner critic 规划"
    assert calls[0]["timeout"] == 10.0
    assert result["source"] == "web"
    assert result["count"] == 2
    assert all(r["source"] == "web" for r in result["results"])
    assert result["results"][0]["url"] == "https://example.com/a"
    assert result["results"][1]["url"] == "https://example.com/b"


def test_web_success_organic_with_key(monkeypatch):
    payload = {"organic": [{"title": "Bing hit", "url": "https://bing.example/1", "description": "desc"}]}
    result, calls = _run(
        monkeypatch,
        {"SEARCH_API_BASE": "https://api.example.com/search", "SEARCH_API_KEY": "sk-test"},
        payload,
    )
    assert calls[0]["headers"]["Authorization"] == "Bearer sk-test"
    assert calls[0]["headers"]["X-API-KEY"] == "sk-test"
    assert result["source"] == "web"
    assert result["results"] == [
        {"title": "Bing hit", "url": "https://bing.example/1", "snippet": "desc", "score": 0.9, "source": "web"}
    ]


def test_web_failure_falls_back_local(monkeypatch):
    result, calls = _run(
        monkeypatch,
        {"SEARCH_API_BASE": "https://api.example.com/search"},
        exc=httpx.ConnectError("boom"),
    )
    assert len(calls) == 1
    assert result["source"] == "local"
    assert all(r["url"].startswith("local://") for r in result["results"])


def test_web_bad_payload_falls_back_local(monkeypatch):
    result, calls = _run(monkeypatch, {"SEARCH_API_BASE": "https://api.example.com/search"}, {"unexpected": [1, 2]})
    assert len(calls) == 1
    assert result["source"] == "local"


def test_web_non_json_falls_back_local(monkeypatch):
    result, calls = _run(monkeypatch, {"SEARCH_API_BASE": "https://api.example.com/search"}, "not json")
    assert len(calls) == 1
    assert result["source"] == "local"
