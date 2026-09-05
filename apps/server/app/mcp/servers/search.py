"""search 真 MCP server — 本地确定性检索（stdio 传输），支持可选真联网

【默认本地确定性实现；设置 SEARCH_API_BASE 后走真联网搜索】
默认实现为内置小型语料 + 词项重叠打分的确定性检索：同一 query 永远返回相同结果，
不依赖网络与第三方 key，保证测试/演示零外部依赖。
设置环境变量 SEARCH_API_BASE（可选配 SEARCH_API_KEY）后，web_search 改为 HTTP GET
{base}?q=...（10s 超时），解析通用 JSON（兼容 DuckDuckGo/Bing/Serper 风格的
results/organic/web 数组的 title+url+snippet 字段并归一化）。
未设置/请求失败/解析失败时静默回退本地语料；每条结果带 source: "web"|"local" 标注。
不加重试（由上层 client.py 负责重试）。

启动: py -m app.mcp.servers.search （cwd=apps/server，见仓库根 mcp.json）
工具: web_search
"""
from __future__ import annotations

import json
import os
import re

import httpx

from mcp.server.mcpserver import MCPServer

_SEARCH_TIMEOUT_S = 10.0

# 内置小型语料（本地确定性检索的检索源，url 用 local:// 标识非外网来源）
_CORPUS: list[dict] = [
    {
        "title": "学习规划方法：目标拆解与时间盒",
        "url": "local://corpus/study-planning-timeboxing",
        "text": "学习规划的核心是把长期目标拆解为可执行任务，使用时间盒 timebox 分配每日学习时段，"
                "并通过每周反思 completion_rate 迭代计划。",
    },
    {
        "title": "间隔重复与遗忘曲线",
        "url": "local://corpus/spaced-repetition",
        "text": "间隔重复 spaced repetition 依据遗忘曲线安排复习节点，配合待办 todo 列表管理每日复习任务。",
    },
    {
        "title": "番茄工作法与专注力",
        "url": "local://corpus/pomodoro",
        "text": "番茄工作法以 25 分钟专注 + 5 分钟休息为循环，适合深度学习时段，可在日历 calendar 中预排。",
    },
    {
        "title": "多智能体规划：planner 与 critic",
        "url": "local://corpus/multi-agent-planning",
        "text": "LangGraph 多智能体工作流中 planner 生成计划、critic 校验冲突、reflector 复盘，"
                "形成可追溯的 6 节点执行序。",
    },
    {
        "title": "RAG 检索增强生成",
        "url": "local://corpus/rag",
        "text": "检索增强生成 RAG 将外部知识库检索结果注入提示词，常用 pgvector 做向量相似度检索。",
    },
    {
        "title": "MCP 协议与工具调用",
        "url": "local://corpus/mcp",
        "text": "MCP(Model Context Protocol) 通过 stdio 传输连接工具 server，客户端 initialize 后 call_tool，"
                "支持超时与重试。",
    },
    {
        "title": "费曼技巧与输出式学习",
        "url": "local://corpus/feynman",
        "text": "费曼技巧强调用自己的话复述知识以检验理解，配合笔记与记忆复习形成闭环。",
    },
    {
        "title": "AI 记忆系统：记忆分层",
        "url": "local://corpus/memory",
        "text": "AI 记忆系统按工作记忆/情景记忆/语义记忆分层存储，写入时去重合并，检索时按相关度注入上下文。",
    },
]

server = MCPServer(name="search", version="0.1.0")

_RESULT_ARRAY_KEYS = ("results", "organic", "web", "organic_results", "data", "items")
_TITLE_KEYS = ("title", "name", "headline")
_URL_KEYS = ("url", "link", "href", "source")
_SNIPPET_KEYS = ("snippet", "description", "text", "abstract", "body", "content")


def _tokens(query: str) -> list[str]:
    # 中英混合分词：连续词/汉字段拆分（确定性，无外部依赖）
    return [t for t in re.findall(r"[\w\u4e00-\u9fff]+", query.lower()) if t]


def _first_str(item: dict, keys: tuple[str, ...]) -> str:
    for k in keys:
        v = item.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _normalize_web(payload: object) -> list[dict]:
    if not isinstance(payload, dict):
        return []
    items: list[dict] = []
    for key in _RESULT_ARRAY_KEYS:
        val = payload.get(key)
        if isinstance(val, list):
            items = [it for it in val if isinstance(it, dict)]
            break
    normalized: list[dict] = []
    for it in items:
        title = _first_str(it, _TITLE_KEYS)
        url = _first_str(it, _URL_KEYS)
        snippet = _first_str(it, _SNIPPET_KEYS)
        if not url:
            continue
        normalized.append(
            {
                "title": title or url,
                "url": url,
                "snippet": snippet[:200],
                "score": 0.9,
                "source": "web",
            }
        )
    return normalized


def _fetch_web(query: str) -> list[dict] | None:
    base = os.getenv("SEARCH_API_BASE", "").strip()
    if not base:
        return None
    try:
        headers: dict[str, str] = {"Accept": "application/json"}
        api_key = os.getenv("SEARCH_API_KEY", "").strip()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
            headers["X-API-KEY"] = api_key
        resp = httpx.get(base, params={"q": query}, headers=headers, timeout=_SEARCH_TIMEOUT_S)
        resp.raise_for_status()
        return _normalize_web(json.loads(resp.text))
    except (httpx.HTTPError, ValueError, TypeError):
        return None


@server.tool(
    name="web_search",
    description="网页搜索（设置 SEARCH_API_BASE 走真联网，否则内置语料+词项重叠打分回退）",
)
def web_search(query: str = "test", limit: int = 3) -> dict:
    web_results = _fetch_web(query or "test")
    if web_results:
        results = web_results[: max(1, int(limit))]
    else:
        tokens = _tokens(query or "test")
        scored: list[tuple[float, int, dict]] = []
        for idx, doc in enumerate(_CORPUS):
            haystack = f"{doc['title']} {doc['text']}".lower()
            hits = sum(1 for t in tokens if t in haystack)
            # 确定性打分：命中词越多分越高，无命中给低保底分；同分保持语料顺序
            score = round(min(0.99, 0.3 + 0.2 * hits), 2) if hits else 0.1
            scored.append((score, idx, doc))
        scored.sort(key=lambda x: (-x[0], x[1]))
        top = scored[: max(1, int(limit))]
        results = [
            {
                "title": doc["title"],
                "url": doc["url"],
                "snippet": doc["text"][:120],
                "score": score,
                "source": "local",
            }
            for score, _idx, doc in top
        ]
    return {
        "results": results,
        "result": {"ok": True, "server": "search", "tool": "web_search"},
        "server": "search",
        "tool": "web_search",
        "query": query,
        "count": len(results),
        "source": "web" if web_results else "local",
    }


if __name__ == "__main__":
    server.run()
