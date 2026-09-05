"""search 真 MCP server — 本地确定性检索（stdio 传输，不接外网）

【本地确定性实现，接真搜索 API 需换实现】
当前实现为内置小型语料 + 词项重叠打分的确定性检索：同一 query 永远返回相同结果，
不依赖网络与第三方 key，保证测试/演示零外部依赖。
若需接真搜索 API（Tavily / Serper / Brave 等），仅需替换本文件 web_search 的内部实现，
工具签名与返回结构（results/result/server/tool/query/count）保持不变即可。

启动: py -m app.mcp.servers.search （cwd=apps/server，见仓库根 mcp.json）
工具: web_search
"""
from __future__ import annotations

import re

from mcp.server.mcpserver import MCPServer

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


def _tokens(query: str) -> list[str]:
    # 中英混合分词：连续词/汉字段拆分（确定性，无外部依赖）
    return [t for t in re.findall(r"[\w\u4e00-\u9fff]+", query.lower()) if t]


@server.tool(
    name="web_search",
    description="本地确定性网页搜索（内置语料+词项重叠打分；接真搜索 API 需换实现）",
)
def web_search(query: str = "test", limit: int = 3) -> dict:
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
    }


if __name__ == "__main__":
    server.run()
